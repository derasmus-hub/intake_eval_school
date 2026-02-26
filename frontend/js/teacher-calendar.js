/**
 * teacher-calendar.js — Student view of teacher availability
 *
 * State-driven rendering: the calendar grid is ONLY built when all
 * preconditions are met (authenticated, teacher selected, data loaded).
 * Otherwise a contextual empty-state message is rendered instead.
 */
(function () {
    'use strict';

    const DAYS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const DAYS_PL = ['Nd', 'Pn', 'Wt', 'Sr', 'Cz', 'Pt', 'So'];
    const MONTHS = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ];
    const MONTHS_PL = [
        'Styczen', 'Luty', 'Marzec', 'Kwiecien', 'Maj', 'Czerwiec',
        'Lipiec', 'Sierpien', 'Wrzesien', 'Pazdziernik', 'Listopad', 'Grudzien'
    ];

    // ── State ────────────────────────────────────────────────────────
    let teachers = [];
    let selectedTeacherId = null;
    let currentYear = new Date().getFullYear();
    let currentMonth = new Date().getMonth(); // 0-indexed
    let availabilityData = null; // null = not loaded, {} = loaded but empty
    let selectedDate = null;
    let sessionData = {}; // keyed by "YYYY-MM-DD" → session object

    // ── Initialization ───────────────────────────────────────────────

    async function init() {
        setMonthNavEnabled(false);
        await loadTeachers();
        renderCalendar();
    }

    // ── State helpers ────────────────────────────────────────────────

    function hasAvailabilityData() {
        return availabilityData &&
               !availabilityData.detail &&
               Object.keys(availabilityData).length > 0;
    }

    function setMonthNavEnabled(enabled) {
        var prev = document.getElementById('prev-month-btn');
        var next = document.getElementById('next-month-btn');
        if (prev) prev.disabled = !enabled;
        if (next) next.disabled = !enabled;
    }

    function renderEmptyState(message) {
        var grid = document.getElementById('calendar-grid');
        var titleEl = document.getElementById('calendar-month-title');
        titleEl.textContent = MONTHS[currentMonth] + ' ' + currentYear + ' / ' + MONTHS_PL[currentMonth];
        grid.innerHTML = '<div class="calendar-empty">' + escapeHtml(message) + '</div>';
    }

    // ── API Calls ────────────────────────────────────────────────────

    async function loadTeachers() {
        const select = document.getElementById('teacher-select');
        try {
            const resp = await apiFetch('/api/students/teachers');

            // 401 — not authenticated; apiFetch redirects, but guard here too
            if (resp.status === 401) {
                renderEmptyState('Please log in to view availability. / Zaloguj sie, aby zobaczyc dostepnosc.');
                return;
            }

            if (!resp.ok) {
                select.innerHTML = '<option value="">Error loading teachers</option>';
                return;
            }
            const data = await resp.json();
            teachers = data.teachers || [];

            if (teachers.length === 0) {
                select.innerHTML = '<option value="">No teachers available / Brak nauczycieli</option>';
                return;
            }

            select.innerHTML = '<option value="">-- Select a teacher / Wybierz nauczyciela --</option>' +
                teachers.map(t => '<option value="' + t.id + '">' + escapeHtml(t.name) + '</option>').join('');

            // Auto-select if only one teacher
            if (teachers.length === 1) {
                select.value = teachers[0].id;
                onTeacherChange();
            }

        } catch (err) {
            console.error('[teacher-calendar] Load teachers error:', err);
            select.innerHTML = '<option value="">Error loading teachers</option>';
        }
    }

    async function loadAvailability(teacherId, year, month) {
        if (!teacherId) return;

        showLoading(true);
        availabilityData = null;

        // Calculate date range for the month view (include prev/next month overflow)
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);

        const startDate = new Date(firstDay);
        startDate.setDate(startDate.getDate() - firstDay.getDay());
        const endDate = new Date(lastDay);
        endDate.setDate(endDate.getDate() + (6 - lastDay.getDay()));

        const fromStr = formatDateISO(startDate);
        const toStr = formatDateISO(endDate);

        try {
            const resp = await apiFetch(
                '/api/students/teacher-availability?teacher_id=' + teacherId + '&from=' + fromStr + '&to=' + toStr
            );

            // 401 — stop, do not parse, render auth message
            if (resp.status === 401) {
                showLoading(false);
                availabilityData = null;
                renderEmptyState('Please log in to view availability. / Zaloguj sie, aby zobaczyc dostepnosc.');
                setMonthNavEnabled(false);
                return;
            }

            if (!resp.ok) {
                var err = await resp.json().catch(function () { return {}; });
                showError(err.detail || 'Could not load availability');
                showLoading(false);
                availabilityData = null;
                renderCalendar();
                return;
            }

            const data = await resp.json();

            // Build lookup by date
            availabilityData = {};
            (data.days || []).forEach(function (day) {
                availabilityData[day.date] = {
                    windows: day.windows || [],
                    available: day.available
                };
            });

            await loadSessions(teacherId, year, month);
            showLoading(false);
            renderCalendar();

        } catch (err) {
            console.error('[teacher-calendar] Load availability error:', err);
            showError('Error loading availability: ' + err.message);
            showLoading(false);
            availabilityData = null;
            renderCalendar();
        }
    }

    async function loadSessions(teacherId, year, month) {
        if (!teacherId) return;
        sessionData = {};

        var firstDay = new Date(year, month, 1);
        var lastDay = new Date(year, month + 1, 0);
        var fromStr = formatDateISO(firstDay);
        var toStr = formatDateISO(lastDay);

        try {
            var resp = await apiFetch(
                '/api/students/teacher-sessions?teacher_id=' + teacherId +
                '&from_date=' + fromStr + '&to_date=' + toStr
            );
            if (!resp.ok) return; // fail silently
            var data = await resp.json();
            (data.sessions || []).forEach(function (s) {
                var dateKey = s.scheduled_at ? s.scheduled_at.substring(0, 10) : null;
                if (dateKey) {
                    sessionData[dateKey] = s;
                }
            });
        } catch (err) {
            console.error('[teacher-calendar] Load sessions error:', err);
            // fail silently — calendar still shows availability
        }
    }

    // ── Event Handlers ───────────────────────────────────────────────

    function onTeacherChange() {
        const select = document.getElementById('teacher-select');
        selectedTeacherId = select.value ? parseInt(select.value, 10) : null;
        selectedDate = null;
        availabilityData = null;
        sessionData = {};
        renderDayDetails();

        // Hide book CTA on teacher change
        var bookCta = document.getElementById('book-cta-section');
        if (bookCta) bookCta.style.display = 'none';

        if (selectedTeacherId) {
            setMonthNavEnabled(true);
            loadAvailability(selectedTeacherId, currentYear, currentMonth);
        } else {
            setMonthNavEnabled(false);
            renderCalendar();
        }
    }

    function prevMonth() {
        if (!selectedTeacherId) return;
        currentMonth--;
        if (currentMonth < 0) {
            currentMonth = 11;
            currentYear--;
        }
        selectedDate = null;
        renderDayDetails();
        loadAvailability(selectedTeacherId, currentYear, currentMonth);
    }

    function nextMonth() {
        if (!selectedTeacherId) return;
        currentMonth++;
        if (currentMonth > 11) {
            currentMonth = 0;
            currentYear++;
        }
        selectedDate = null;
        renderDayDetails();
        loadAvailability(selectedTeacherId, currentYear, currentMonth);
    }

    function selectDay(dateStr) {
        selectedDate = dateStr;
        renderCalendar();
        renderDayDetails();

        var dayData = availabilityData ? availabilityData[dateStr] : null;
        var bookCta = document.getElementById('book-cta-section');
        var hasSession = !!sessionData[dateStr];

        // Show request form only if day is available and no session already exists
        if (dayData && dayData.available && dayData.windows.length > 0 && !hasSession) {
            bookCta.style.display = 'block';
            // Clear any previous status message
            var statusEl = document.getElementById('book-cta-status');
            if (statusEl) statusEl.innerHTML = '';
        } else {
            bookCta.style.display = 'none';
        }
    }

    // ── Rendering ────────────────────────────────────────────────────

    function renderCalendar() {
        var grid = document.getElementById('calendar-grid');
        var titleEl = document.getElementById('calendar-month-title');

        // Always update the month title
        titleEl.textContent = MONTHS[currentMonth] + ' ' + currentYear + ' / ' + MONTHS_PL[currentMonth];

        // ── Guard 1: no teacher selected ──
        if (!selectedTeacherId) {
            grid.innerHTML = '<div class="calendar-empty">Select a teacher to view availability. / Wybierz nauczyciela, aby zobaczyc dostepnosc.</div>';
            setMonthNavEnabled(false);
            return;
        }

        // ── Guard 2: data not yet loaded (loading in progress) ──
        if (availabilityData === null) {
            return; // loading spinner is already visible
        }

        // ── Guard 3: data loaded but empty or errored ──
        if (availabilityData.detail || Object.keys(availabilityData).length === 0) {
            grid.innerHTML = '<div class="calendar-empty">This teacher has no available hours set. / Ten nauczyciel nie ma ustalonych godzin.</div>';
            return;
        }

        // ── All guards passed — build the grid ──
        var html = '';

        // Day headers
        html += '<div class="calendar-row calendar-header-row">';
        for (var i = 0; i < 7; i++) {
            html += '<div class="calendar-header-cell">' + DAYS_SHORT[i] + '<br><span class="meta">' + DAYS_PL[i] + '</span></div>';
        }
        html += '</div>';

        // Month geometry
        var firstDay = new Date(currentYear, currentMonth, 1);
        var lastDay = new Date(currentYear, currentMonth + 1, 0);
        var totalDays = lastDay.getDate();
        var startDayOfWeek = firstDay.getDay();

        var prevMonthLastDay = new Date(currentYear, currentMonth, 0).getDate();
        var prevMonthStart = prevMonthLastDay - startDayOfWeek + 1;

        var today = new Date();
        today.setHours(0, 0, 0, 0);
        var todayStr = formatDateISO(today);

        var dayCounter = 1;
        var nextMonthCounter = 1;

        for (var week = 0; week < 6; week++) {
            html += '<div class="calendar-row">';

            for (var dayOfWeek = 0; dayOfWeek < 7; dayOfWeek++) {
                var cellIndex = week * 7 + dayOfWeek;

                if (cellIndex < startDayOfWeek) {
                    var prevDay = prevMonthStart + cellIndex;
                    var pm = currentMonth === 0 ? 11 : currentMonth - 1;
                    var py = currentMonth === 0 ? currentYear - 1 : currentYear;
                    html += renderDayCell(prevDay, formatDateISO(new Date(py, pm, prevDay)), 'other-month', false, true);
                } else if (dayCounter > totalDays) {
                    var nm = currentMonth === 11 ? 0 : currentMonth + 1;
                    var ny = currentMonth === 11 ? currentYear + 1 : currentYear;
                    html += renderDayCell(nextMonthCounter, formatDateISO(new Date(ny, nm, nextMonthCounter)), 'other-month', false, false);
                    nextMonthCounter++;
                } else {
                    var dateStr = formatDateISO(new Date(currentYear, currentMonth, dayCounter));
                    var isToday = dateStr === todayStr;
                    var isPast = new Date(dateStr) < today;
                    html += renderDayCell(dayCounter, dateStr, 'current-month', isToday, isPast);
                    dayCounter++;
                }
            }

            html += '</div>';

            if (dayCounter > totalDays && (week + 1) * 7 >= startDayOfWeek + totalDays) {
                break;
            }
        }

        grid.innerHTML = html;
    }

    function renderDayCell(dayNum, dateStr, monthClass, isToday, isPast) {
        var dayData = availabilityData ? availabilityData[dateStr] : null;
        var statusClass = 'cal-disabled';
        var clickable = false;

        if (dayData !== undefined && dayData !== null) {
            if (isPast) {
                statusClass = 'cal-past';
            } else if (dayData.available && dayData.windows && dayData.windows.length > 0) {
                statusClass = 'cal-available';
                clickable = true;
            } else if (!dayData.available) {
                statusClass = 'cal-unavailable';
            } else {
                statusClass = 'cal-no-hours';
            }
        } else if (isPast) {
            statusClass = 'cal-past';
        }

        var selectedClass = dateStr === selectedDate ? 'cal-selected' : '';
        var todayClass = isToday ? 'cal-today' : '';
        var onClick = clickable ? ' onclick="selectDay(\'' + dateStr + '\')"' : '';
        var cursorStyle = clickable ? 'cursor:pointer;' : '';

        var windowInfo = '';
        if (clickable && dayData && dayData.windows.length > 0) {
            windowInfo = '<span class="cal-window-count">' + dayData.windows.length + ' slot' + (dayData.windows.length > 1 ? 's' : '') + '</span>';
        }

        var sessionBadge = '';
        var sess = sessionData[dateStr];
        if (sess) {
            var badgeClass = sess.status === 'confirmed' ? 'confirmed' : 'pending';
            var badgeLabel = sess.status === 'confirmed' ? 'Conf' : 'Req';
            sessionBadge = '<span class="cal-session-badge ' + badgeClass + '">' + badgeLabel + '</span>';
            // Make days with sessions clickable even if not available
            if (!clickable) {
                clickable = true;
                onClick = ' onclick="selectDay(\'' + dateStr + '\')"';
                cursorStyle = 'cursor:pointer;';
            }
        }

        return '<div class="calendar-cell ' + monthClass + ' ' + statusClass + ' ' + selectedClass + ' ' + todayClass + '"' + onClick + ' style="' + cursorStyle + '">' +
            '<span class="cal-day-num">' + dayNum + '</span>' +
            windowInfo +
            sessionBadge +
        '</div>';
    }

    function renderDayDetails() {
        var titleEl = document.getElementById('day-details-title');
        var contentEl = document.getElementById('day-details-content');

        if (!selectedDate) {
            titleEl.textContent = 'Select a Day / Wybierz dzien';
            contentEl.innerHTML =
                '<p class="meta">Click on a day in the calendar above to see available time slots.</p>' +
                '<p class="meta"><em>Kliknij dzien w kalendarzu powyzej, aby zobaczyc dostepne godziny.</em></p>';
            return;
        }

        var dateObj = new Date(selectedDate + 'T00:00:00');
        var dateDisplay = dateObj.toLocaleDateString('en-GB', {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
            year: 'numeric'
        });

        titleEl.textContent = dateDisplay;

        var dayData = availabilityData ? availabilityData[selectedDate] : null;

        if (!dayData) {
            contentEl.innerHTML =
                '<p class="meta">No availability data for this day.</p>' +
                '<p class="meta"><em>Brak danych o dostepnosci na ten dzien.</em></p>';
            return;
        }

        if (!dayData.available) {
            contentEl.innerHTML =
                '<div class="day-detail-unavailable">' +
                    '<p><strong>Teacher is not available on this day.</strong></p>' +
                    '<p><em>Nauczyciel nie jest dostepny w tym dniu.</em></p>' +
                '</div>';
            return;
        }

        if (!dayData.windows || dayData.windows.length === 0) {
            contentEl.innerHTML =
                '<div class="day-detail-no-hours">' +
                    '<p><strong>No hours set for this day.</strong></p>' +
                    '<p><em>Brak ustalonych godzin na ten dzien.</em></p>' +
                '</div>';
            return;
        }

        var html =
            '<div class="day-detail-available">' +
                '<p><strong>Available time slots / Dostepne godziny:</strong></p>' +
                '<div class="time-slots-grid">';

        dayData.windows.forEach(function (w) {
            html +=
                '<div class="time-slot">' +
                    '<span class="time-slot-time">' + escapeHtml(w.start) + ' - ' + escapeHtml(w.end) + '</span>' +
                    '<span class="time-slot-label">Available / Dostepny</span>' +
                '</div>';
        });

        html += '</div>';

        // Show session info if one exists for this day
        var sess = sessionData[selectedDate];
        if (sess) {
            var sessionTime = sess.scheduled_at ? sess.scheduled_at.substring(11, 16) : '';
            if (sess.status === 'confirmed') {
                html +=
                    '<div class="cal-session-info confirmed">' +
                        '<strong>Session confirmed! / Sesja potwierdzona!</strong>' +
                        (sessionTime ? '<br>Time / Godzina: ' + escapeHtml(sessionTime) : '') +
                        '<br>Duration / Czas: ' + sess.duration_min + ' min' +
                    '</div>';
            } else {
                html +=
                    '<div class="cal-session-info pending">' +
                        '<strong>You have a pending request / Masz oczekujaca prosbe</strong>' +
                        (sessionTime ? '<br>Time / Godzina: ' + escapeHtml(sessionTime) : '') +
                        '<br>Duration / Czas: ' + sess.duration_min + ' min' +
                    '</div>';
            }
        } else {
            html +=
                '<p class="meta" style="margin-top:1rem;">' +
                    'Use the form below to request a session at one of these times.' +
                    '<br><em>Uzyj formularza ponizej, aby zarezerwowac sesje.</em>' +
                '</p>';
        }

        html += '</div>';

        contentEl.innerHTML = html;
    }

    // ── Helpers ──────────────────────────────────────────────────────

    function formatDateISO(date) {
        var year = date.getFullYear();
        var month = String(date.getMonth() + 1).padStart(2, '0');
        var day = String(date.getDate()).padStart(2, '0');
        return year + '-' + month + '-' + day;
    }

    function showLoading(show) {
        var loadingEl = document.getElementById('calendar-loading');
        var gridEl = document.getElementById('calendar-grid');
        var errorEl = document.getElementById('calendar-error');

        if (show) {
            loadingEl.classList.remove('hidden');
            gridEl.style.opacity = '0.5';
            errorEl.classList.add('hidden');
        } else {
            loadingEl.classList.add('hidden');
            gridEl.style.opacity = '1';
        }
    }

    function showError(message) {
        var errorEl = document.getElementById('calendar-error');
        errorEl.innerHTML = '<p>' + escapeHtml(message) + '</p>';
        errorEl.classList.remove('hidden');
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    async function submitCalendarRequest() {
        if (!selectedDate || !selectedTeacherId) return;

        var timeInput = document.getElementById('session-time');
        var durationSelect = document.getElementById('session-duration');
        var statusEl = document.getElementById('book-cta-status');

        var time = timeInput ? timeInput.value : '10:00';
        var duration = durationSelect ? parseInt(durationSelect.value, 10) : 60;
        var scheduledAt = selectedDate + 'T' + time + ':00';

        statusEl.innerHTML = '<span style="color:#94a3b8;">Submitting... / Wysylanie...</span>';

        try {
            var resp = await apiFetch('/api/student/me/sessions/request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    teacher_id: selectedTeacherId,
                    scheduled_at: scheduledAt,
                    duration_min: duration
                })
            });

            if (!resp.ok) {
                var err = await resp.json().catch(function () { return {}; });
                statusEl.innerHTML = '<span style="color:#f87171;">' + escapeHtml(err.detail || 'Request failed') + '</span>';
                return;
            }

            statusEl.innerHTML = '<span style="color:#34d399;">Request sent! / Prosba wyslana!</span>';

            // Refresh session data and re-render
            await loadSessions(selectedTeacherId, currentYear, currentMonth);
            renderCalendar();
            renderDayDetails();

            // Hide the form since a session now exists for this day
            var bookCta = document.getElementById('book-cta-section');
            if (bookCta) bookCta.style.display = 'none';

        } catch (err) {
            console.error('[teacher-calendar] Submit request error:', err);
            statusEl.innerHTML = '<span style="color:#f87171;">Error: ' + escapeHtml(err.message) + '</span>';
        }
    }

    // ── Expose Functions Globally ────────────────────────────────────

    window.onTeacherChange = onTeacherChange;
    window.prevMonth = prevMonth;
    window.nextMonth = nextMonth;
    window.selectDay = selectDay;
    window.submitCalendarRequest = submitCalendarRequest;

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
