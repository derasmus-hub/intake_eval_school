/**
 * teacher-dashboard-calendar.js — Monthly calendar on the teacher dashboard
 *
 * Shows sessions overlaid on availability windows. Reuses the existing
 * calendar CSS classes from teacher-calendar.js / style.css.
 *
 * All DOM IDs are prefixed with "tcal-" to avoid collisions with other
 * calendar instances (e.g. the student-facing teacher-calendar.js).
 */
(function () {
    'use strict';

    var DAYS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    var DAYS_PL   = ['Nd', 'Pn', 'Wt', 'Sr', 'Cz', 'Pt', 'So'];
    var MONTHS = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ];
    var MONTHS_PL = [
        'Styczen', 'Luty', 'Marzec', 'Kwiecien', 'Maj', 'Czerwiec',
        'Lipiec', 'Sierpien', 'Wrzesien', 'Pazdziernik', 'Listopad', 'Grudzien'
    ];
    var DAY_NAMES_MAP = {
        'sunday': 0, 'monday': 1, 'tuesday': 2, 'wednesday': 3,
        'thursday': 4, 'friday': 5, 'saturday': 6
    };

    // ── State ────────────────────────────────────────────────────────
    var currentYear  = new Date().getFullYear();
    var currentMonth = new Date().getMonth(); // 0-indexed
    var selectedDate = null;
    var calSessions  = {}; // { "YYYY-MM-DD": [session, ...] }
    var weeklyWindows = []; // from /api/teacher/availability
    var overrides     = []; // from /api/teacher/availability
    var dataLoaded    = false;

    // ── Initialization ───────────────────────────────────────────────

    function initCalendar() {
        var grid = document.getElementById('tcal-grid');
        if (!grid) return; // not on teacher dashboard
        loadCalendarData();
    }

    // ── Data Loading ────────────────────────────────────────────────

    function loadCalendarData() {
        dataLoaded = false;
        showLoading(true);

        var firstDay = new Date(currentYear, currentMonth, 1);
        var lastDay  = new Date(currentYear, currentMonth + 1, 0);
        var fromStr  = formatDateISO(firstDay);
        var toStr    = formatDateISO(lastDay);

        var sessionsPromise = apiFetch(
            '/api/teacher/sessions?from_date=' + fromStr + '&to_date=' + toStr
        ).then(function (resp) {
            if (!resp.ok) return { sessions: [] };
            return resp.json();
        }).catch(function () {
            return { sessions: [] };
        });

        var availPromise = apiFetch('/api/teacher/availability').then(function (resp) {
            if (!resp.ok) return { windows: [], overrides: [] };
            return resp.json();
        }).catch(function () {
            return { windows: [], overrides: [] };
        });

        Promise.all([sessionsPromise, availPromise]).then(function (results) {
            var sessData  = results[0];
            var availData = results[1];

            // Group sessions by date
            calSessions = {};
            (sessData.sessions || []).forEach(function (s) {
                var dateKey = s.scheduled_at ? s.scheduled_at.substring(0, 10) : null;
                if (dateKey) {
                    if (!calSessions[dateKey]) calSessions[dateKey] = [];
                    calSessions[dateKey].push(s);
                }
            });

            weeklyWindows = availData.windows || [];
            overrides = availData.overrides || [];

            dataLoaded = true;
            showLoading(false);
            renderCalendar();
        });
    }

    // ── Calendar Rendering ──────────────────────────────────────────

    function renderCalendar() {
        var grid    = document.getElementById('tcal-grid');
        var titleEl = document.getElementById('tcal-month-title');
        if (!grid || !titleEl) return;

        titleEl.textContent = MONTHS[currentMonth] + ' ' + currentYear + ' / ' + MONTHS_PL[currentMonth];

        if (!dataLoaded) {
            grid.innerHTML = '<div class="calendar-empty">Loading... / Ladowanie...</div>';
            return;
        }

        var html = '';

        // Day headers
        html += '<div class="calendar-row calendar-header-row">';
        for (var i = 0; i < 7; i++) {
            html += '<div class="calendar-header-cell">' + DAYS_SHORT[i] +
                    '<br><span class="meta">' + DAYS_PL[i] + '</span></div>';
        }
        html += '</div>';

        // Month geometry
        var firstDay       = new Date(currentYear, currentMonth, 1);
        var lastDay        = new Date(currentYear, currentMonth + 1, 0);
        var totalDays      = lastDay.getDate();
        var startDayOfWeek = firstDay.getDay();

        var prevMonthLastDay = new Date(currentYear, currentMonth, 0).getDate();

        var today = new Date();
        today.setHours(0, 0, 0, 0);
        var todayStr = formatDateISO(today);

        var dayCounter      = 1;
        var nextMonthCounter = 1;

        for (var week = 0; week < 6; week++) {
            html += '<div class="calendar-row">';

            for (var dayOfWeek = 0; dayOfWeek < 7; dayOfWeek++) {
                var cellIndex = week * 7 + dayOfWeek;

                if (cellIndex < startDayOfWeek) {
                    // Previous month overflow
                    var prevDay = prevMonthLastDay - startDayOfWeek + 1 + cellIndex;
                    var pm = currentMonth === 0 ? 11 : currentMonth - 1;
                    var py = currentMonth === 0 ? currentYear - 1 : currentYear;
                    html += renderDayCell(prevDay, formatDateISO(new Date(py, pm, prevDay)), true, false);
                } else if (dayCounter > totalDays) {
                    // Next month overflow
                    var nm = currentMonth === 11 ? 0 : currentMonth + 1;
                    var ny = currentMonth === 11 ? currentYear + 1 : currentYear;
                    html += renderDayCell(nextMonthCounter, formatDateISO(new Date(ny, nm, nextMonthCounter)), true, false);
                    nextMonthCounter++;
                } else {
                    var dateStr = formatDateISO(new Date(currentYear, currentMonth, dayCounter));
                    var isToday = dateStr === todayStr;
                    html += renderDayCell(dayCounter, dateStr, false, isToday);
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

    function renderDayCell(dayNum, dateStr, isOtherMonth, isToday) {
        var sessions = calSessions[dateStr] || [];
        var avail    = getAvailabilityForDate(dateStr);
        var hasAvail = avail.length > 0;
        var isSelected = dateStr === selectedDate;

        var classes = ['calendar-cell'];
        if (isOtherMonth)   classes.push('other-month');
        if (isToday)        classes.push('cal-today');
        if (isSelected)     classes.push('cal-selected');
        if (hasAvail && !isOtherMonth) classes.push('tcal-has-avail');

        var onClick = (!isOtherMonth) ? ' onclick="tcalSelectDay(\'' + dateStr + '\')"' : '';
        var cursor  = (!isOtherMonth) ? 'cursor:pointer;' : '';

        var inner = '<span class="cal-day-num">' + dayNum + '</span>';

        // Session count badge
        if (sessions.length > 0) {
            var confirmed = sessions.filter(function (s) { return s.status === 'confirmed'; }).length;
            var requested = sessions.length - confirmed;

            if (confirmed > 0) {
                inner += '<span class="cal-session-badge confirmed">' + confirmed + ' conf</span>';
            }
            if (requested > 0) {
                inner += '<span class="cal-session-badge pending">' + requested + ' req</span>';
            }
        } else if (hasAvail && !isOtherMonth) {
            // Show availability hint if no sessions
            inner += '<span class="cal-window-count">' + avail.length + ' slot' + (avail.length > 1 ? 's' : '') + '</span>';
        }

        return '<div class="' + classes.join(' ') + '"' + onClick + ' style="' + cursor + '">' +
               inner + '</div>';
    }

    // ── Day Details ─────────────────────────────────────────────────

    function renderDayDetails() {
        var container = document.getElementById('tcal-day-details');
        if (!container) return;

        if (!selectedDate) {
            container.innerHTML = '';
            return;
        }

        var dateObj = new Date(selectedDate + 'T00:00:00');
        var dateDisplay = dateObj.toLocaleDateString('en-GB', {
            weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
        });

        var sessions = calSessions[selectedDate] || [];
        var avail    = getAvailabilityForDate(selectedDate);

        var html = '<div class="detail-panel" style="margin-top:0;">';
        html += '<h3>' + escapeHtml(dateDisplay) + '</h3>';

        // Sessions list
        if (sessions.length > 0) {
            html += '<p style="margin:0.5rem 0;"><strong>' + sessions.length + ' session' +
                    (sessions.length > 1 ? 's' : '') + '</strong></p>';
            sessions.forEach(function (s) {
                html += renderSessionCard(s);
            });
        } else {
            html += '<p class="meta" style="margin:0.5rem 0;">No sessions on this day. / Brak sesji w tym dniu.</p>';
        }

        // Availability windows
        if (avail.length > 0) {
            html += '<div style="margin-top:0.75rem;">';
            html += '<p class="meta"><strong>Availability windows / Godziny dostepnosci:</strong></p>';
            html += '<div class="time-slots-grid" style="margin-top:0.4rem;">';
            avail.forEach(function (w) {
                html += '<div class="time-slot">' +
                    '<span class="time-slot-time">' + escapeHtml(w.start_time) + ' - ' + escapeHtml(w.end_time) + '</span>' +
                    '<span class="time-slot-label">Available</span>' +
                '</div>';
            });
            html += '</div></div>';
        }

        html += '</div>';
        container.innerHTML = html;
    }

    function renderSessionCard(s) {
        var time = s.scheduled_at ? s.scheduled_at.substring(11, 16) : '';
        var badgeClass = s.status === 'confirmed' ? 'session-badge-confirmed'
                       : s.status === 'requested' ? 'session-badge-requested'
                       : 'session-badge-cancelled';
        var statusLabel = s.status === 'confirmed' ? 'Confirmed'
                        : s.status === 'requested' ? 'Pending'
                        : s.status.charAt(0).toUpperCase() + s.status.slice(1);

        var html = '<div class="tcal-day-card">';
        html += '<div style="display:flex;justify-content:space-between;align-items:flex-start;">';
        html += '<div>';
        html += '<strong>' + escapeHtml(s.student_name || 'Student #' + s.student_id) + '</strong>';
        if (s.current_level) {
            html += ' <span class="level-badge" style="font-size:0.75rem;padding:0.1rem 0.4rem;">' +
                    escapeHtml(s.current_level) + '</span>';
        }
        html += '<br><span class="meta">' + escapeHtml(time) + ' &middot; ' + s.duration_min + ' min</span>';
        if (s.notes) {
            html += '<br><span class="meta" style="font-style:italic;">' + escapeHtml(s.notes) + '</span>';
        }
        html += '</div>';
        html += '<span class="session-badge ' + badgeClass + '">' + statusLabel + '</span>';
        html += '</div>';

        // Action buttons
        if (s.status === 'requested') {
            html += '<div style="display:flex;gap:0.4rem;margin-top:0.5rem;flex-wrap:wrap;">';
            html += '<button class="btn btn-sm btn-primary" onclick="tcalConfirmSession(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;">Confirm</button>';
            html += '<button class="btn btn-sm" onclick="tcalCancelSession(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.3);">Cancel</button>';
            html += '</div>';
        } else if (s.status === 'confirmed') {
            html += '<div style="display:flex;gap:0.4rem;margin-top:0.5rem;flex-wrap:wrap;">';
            html += '<button class="btn btn-sm btn-secondary" onclick="openNotesModal(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;">Log Notes</button>';
            html += '<button class="btn btn-sm" onclick="tcalCancelSession(' + s.id + ')" style="font-size:0.8rem;padding:0.3rem 0.6rem;background:rgba(239,68,68,0.2);color:#fca5a5;border:1px solid rgba(239,68,68,0.3);">Cancel</button>';
            html += '</div>';
        }

        html += '</div>';
        return html;
    }

    // ── Availability Computation ────────────────────────────────────

    function getAvailabilityForDate(dateStr) {
        var dateObj = new Date(dateStr + 'T00:00:00');
        var dayOfWeek = dateObj.getDay(); // 0=Sunday

        // Check overrides first
        for (var i = 0; i < overrides.length; i++) {
            if (overrides[i].date === dateStr) {
                if (!overrides[i].is_available) return [];
                // If override has custom windows, use those
                if (overrides[i].windows && overrides[i].windows.length > 0) {
                    return overrides[i].windows;
                }
                // Override says available but no custom windows — fall through to weekly
                break;
            }
        }

        // Match weekly windows by day of week
        var result = [];
        weeklyWindows.forEach(function (w) {
            var wDay = DAY_NAMES_MAP[w.day_of_week.toLowerCase()];
            if (wDay === dayOfWeek) {
                result.push(w);
            }
        });
        return result;
    }

    // ── Actions ─────────────────────────────────────────────────────

    function tcalConfirmSession(sessionId) {
        if (typeof window.confirmSession === 'function') {
            window.confirmSession(sessionId);
        }
    }

    function tcalCancelSession(sessionId) {
        if (typeof window.cancelSession === 'function') {
            window.cancelSession(sessionId);
        }
    }

    function tcalPrevMonth() {
        currentMonth--;
        if (currentMonth < 0) {
            currentMonth = 11;
            currentYear--;
        }
        selectedDate = null;
        renderDayDetails();
        loadCalendarData();
    }

    function tcalNextMonth() {
        currentMonth++;
        if (currentMonth > 11) {
            currentMonth = 0;
            currentYear++;
        }
        selectedDate = null;
        renderDayDetails();
        loadCalendarData();
    }

    function tcalSelectDay(dateStr) {
        selectedDate = (selectedDate === dateStr) ? null : dateStr;
        renderCalendar();
        renderDayDetails();
    }

    function tcalRefresh() {
        loadCalendarData();
    }

    // ── Utilities ───────────────────────────────────────────────────

    function formatDateISO(date) {
        var year  = date.getFullYear();
        var month = String(date.getMonth() + 1).padStart(2, '0');
        var day   = String(date.getDate()).padStart(2, '0');
        return year + '-' + month + '-' + day;
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    function showLoading(show) {
        var loadingEl = document.getElementById('tcal-loading');
        var gridEl    = document.getElementById('tcal-grid');
        if (!loadingEl || !gridEl) return;

        if (show) {
            loadingEl.classList.remove('hidden');
            gridEl.style.opacity = '0.5';
        } else {
            loadingEl.classList.add('hidden');
            gridEl.style.opacity = '1';
        }
    }

    // ── Expose Globally ─────────────────────────────────────────────

    window.tcalPrevMonth     = tcalPrevMonth;
    window.tcalNextMonth     = tcalNextMonth;
    window.tcalSelectDay     = tcalSelectDay;
    window.tcalConfirmSession = tcalConfirmSession;
    window.tcalCancelSession  = tcalCancelSession;
    window.tcalRefresh        = tcalRefresh;

    // ── Initialize on DOM ready ─────────────────────────────────────

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCalendar);
    } else {
        initCalendar();
    }
})();
