/**
 * teacher-calendar.js — Student view of teacher availability
 *
 * Shows a monthly calendar with available/unavailable days.
 * Clicking a day shows the available time windows.
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

    // State
    let teachers = [];
    let selectedTeacherId = null;
    let currentYear = new Date().getFullYear();
    let currentMonth = new Date().getMonth(); // 0-indexed
    let availabilityData = {}; // { "2026-02-10": { windows: [...], available: true }, ... }
    let selectedDate = null;

    // ── Initialization ─────────────────────────────────────────────────

    async function init() {
        await loadTeachers();
        renderCalendar();
    }

    // ── API Calls ──────────────────────────────────────────────────────

    async function loadTeachers() {
        const select = document.getElementById('teacher-select');
        try {
            const resp = await apiFetch('/api/students/teachers');
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
                teachers.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('');

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
        availabilityData = {};

        // Calculate date range for the month view (include prev/next month overflow)
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);

        // Extend range to cover calendar grid (might show days from prev/next month)
        const startDate = new Date(firstDay);
        startDate.setDate(startDate.getDate() - firstDay.getDay()); // Start from Sunday
        const endDate = new Date(lastDay);
        endDate.setDate(endDate.getDate() + (6 - lastDay.getDay())); // End on Saturday

        const fromStr = formatDateISO(startDate);
        const toStr = formatDateISO(endDate);

        try {
            const resp = await apiFetch(
                `/api/students/teacher-availability?teacher_id=${teacherId}&from=${fromStr}&to=${toStr}`
            );

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                showError(err.detail || 'Could not load availability');
                showLoading(false);
                return;
            }

            const data = await resp.json();

            // Build lookup by date
            (data.days || []).forEach(day => {
                availabilityData[day.date] = {
                    windows: day.windows || [],
                    available: day.available
                };
            });

            showLoading(false);
            renderCalendar();

        } catch (err) {
            console.error('[teacher-calendar] Load availability error:', err);
            showError('Error loading availability: ' + err.message);
            showLoading(false);
        }
    }

    // ── Event Handlers ─────────────────────────────────────────────────

    function onTeacherChange() {
        const select = document.getElementById('teacher-select');
        selectedTeacherId = select.value ? parseInt(select.value, 10) : null;
        selectedDate = null;
        renderDayDetails();

        if (selectedTeacherId) {
            loadAvailability(selectedTeacherId, currentYear, currentMonth);
        } else {
            availabilityData = {};
            renderCalendar();
        }
    }

    function prevMonth() {
        currentMonth--;
        if (currentMonth < 0) {
            currentMonth = 11;
            currentYear--;
        }
        selectedDate = null;
        renderDayDetails();

        if (selectedTeacherId) {
            loadAvailability(selectedTeacherId, currentYear, currentMonth);
        } else {
            renderCalendar();
        }
    }

    function nextMonth() {
        currentMonth++;
        if (currentMonth > 11) {
            currentMonth = 0;
            currentYear++;
        }
        selectedDate = null;
        renderDayDetails();

        if (selectedTeacherId) {
            loadAvailability(selectedTeacherId, currentYear, currentMonth);
        } else {
            renderCalendar();
        }
    }

    function selectDay(dateStr) {
        selectedDate = dateStr;
        renderCalendar(); // Re-render to show selection
        renderDayDetails();

        // Show book CTA if day has availability
        const dayData = availabilityData[dateStr];
        const bookCta = document.getElementById('book-cta-section');
        if (dayData && dayData.available && dayData.windows.length > 0) {
            bookCta.style.display = 'block';
        } else {
            bookCta.style.display = 'none';
        }
    }

    // ── Rendering ──────────────────────────────────────────────────────

    function renderCalendar() {
        const grid = document.getElementById('calendar-grid');
        const titleEl = document.getElementById('calendar-month-title');

        // Update title
        titleEl.textContent = `${MONTHS[currentMonth]} ${currentYear} / ${MONTHS_PL[currentMonth]}`;

        // Build calendar grid
        let html = '';

        // Day headers
        html += '<div class="calendar-row calendar-header-row">';
        for (let i = 0; i < 7; i++) {
            html += `<div class="calendar-header-cell">${DAYS_SHORT[i]}<br><span class="meta">${DAYS_PL[i]}</span></div>`;
        }
        html += '</div>';

        // Get first day of month and total days
        const firstDay = new Date(currentYear, currentMonth, 1);
        const lastDay = new Date(currentYear, currentMonth + 1, 0);
        const totalDays = lastDay.getDate();
        const startDayOfWeek = firstDay.getDay(); // 0 = Sunday

        // Calculate previous month days to show
        const prevMonthLastDay = new Date(currentYear, currentMonth, 0).getDate();
        const prevMonthStart = prevMonthLastDay - startDayOfWeek + 1;

        // Build weeks
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const todayStr = formatDateISO(today);

        let dayCounter = 1;
        let nextMonthCounter = 1;

        for (let week = 0; week < 6; week++) {
            html += '<div class="calendar-row">';

            for (let dayOfWeek = 0; dayOfWeek < 7; dayOfWeek++) {
                const cellIndex = week * 7 + dayOfWeek;

                if (cellIndex < startDayOfWeek) {
                    // Previous month
                    const prevDay = prevMonthStart + cellIndex;
                    const prevMonth = currentMonth === 0 ? 11 : currentMonth - 1;
                    const prevYear = currentMonth === 0 ? currentYear - 1 : currentYear;
                    const dateStr = formatDateISO(new Date(prevYear, prevMonth, prevDay));
                    html += renderDayCell(prevDay, dateStr, 'other-month');
                } else if (dayCounter > totalDays) {
                    // Next month
                    const nextMonth = currentMonth === 11 ? 0 : currentMonth + 1;
                    const nextYear = currentMonth === 11 ? currentYear + 1 : currentYear;
                    const dateStr = formatDateISO(new Date(nextYear, nextMonth, nextMonthCounter));
                    html += renderDayCell(nextMonthCounter, dateStr, 'other-month');
                    nextMonthCounter++;
                } else {
                    // Current month
                    const dateStr = formatDateISO(new Date(currentYear, currentMonth, dayCounter));
                    const isToday = dateStr === todayStr;
                    const isPast = new Date(dateStr) < today;
                    html += renderDayCell(dayCounter, dateStr, 'current-month', isToday, isPast);
                    dayCounter++;
                }
            }

            html += '</div>';

            // Stop if we've rendered all days and completed the week
            if (dayCounter > totalDays && (week + 1) * 7 >= startDayOfWeek + totalDays) {
                break;
            }
        }

        grid.innerHTML = html;
    }

    function renderDayCell(dayNum, dateStr, monthClass, isToday = false, isPast = false) {
        const dayData = availabilityData[dateStr];
        let statusClass = 'cal-unknown';
        let clickable = false;

        if (selectedTeacherId && dayData !== undefined) {
            if (isPast) {
                statusClass = 'cal-past';
            } else if (dayData.available && dayData.windows.length > 0) {
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

        const selectedClass = dateStr === selectedDate ? 'cal-selected' : '';
        const todayClass = isToday ? 'cal-today' : '';
        const onClick = clickable ? `onclick="selectDay('${dateStr}')"` : '';
        const cursorStyle = clickable ? 'cursor:pointer;' : '';

        // Show window count for available days
        let windowInfo = '';
        if (dayData && dayData.available && dayData.windows.length > 0 && !isPast) {
            windowInfo = `<span class="cal-window-count">${dayData.windows.length} slot${dayData.windows.length > 1 ? 's' : ''}</span>`;
        }

        return `<div class="calendar-cell ${monthClass} ${statusClass} ${selectedClass} ${todayClass}" ${onClick} style="${cursorStyle}">
            <span class="cal-day-num">${dayNum}</span>
            ${windowInfo}
        </div>`;
    }

    function renderDayDetails() {
        const titleEl = document.getElementById('day-details-title');
        const contentEl = document.getElementById('day-details-content');

        if (!selectedDate) {
            titleEl.textContent = 'Select a Day / Wybierz dzien';
            contentEl.innerHTML = `
                <p class="meta">Click on a day in the calendar above to see available time slots.</p>
                <p class="meta"><em>Kliknij dzien w kalendarzu powyzej, aby zobaczyc dostepne godziny.</em></p>
            `;
            return;
        }

        const dateObj = new Date(selectedDate + 'T00:00:00');
        const dateStr = dateObj.toLocaleDateString('en-GB', {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
            year: 'numeric'
        });

        titleEl.textContent = dateStr;

        const dayData = availabilityData[selectedDate];

        if (!dayData) {
            contentEl.innerHTML = `
                <p class="meta">No availability data for this day.</p>
                <p class="meta"><em>Brak danych o dostepnosci na ten dzien.</em></p>
            `;
            return;
        }

        if (!dayData.available) {
            contentEl.innerHTML = `
                <div class="day-detail-unavailable">
                    <p><strong>Teacher is not available on this day.</strong></p>
                    <p><em>Nauczyciel nie jest dostepny w tym dniu.</em></p>
                </div>
            `;
            return;
        }

        if (dayData.windows.length === 0) {
            contentEl.innerHTML = `
                <div class="day-detail-no-hours">
                    <p><strong>No hours set for this day.</strong></p>
                    <p><em>Brak ustalonych godzin na ten dzien.</em></p>
                </div>
            `;
            return;
        }

        // Show available time slots
        let html = `
            <div class="day-detail-available">
                <p><strong>Available time slots / Dostepne godziny:</strong></p>
                <div class="time-slots-grid">
        `;

        dayData.windows.forEach(w => {
            const start = w.start;
            const end = w.end;
            html += `
                <div class="time-slot">
                    <span class="time-slot-time">${start} - ${end}</span>
                    <span class="time-slot-label">Available / Dostepny</span>
                </div>
            `;
        });

        html += `
                </div>
                <p class="meta" style="margin-top:1rem;">
                    To book a session at one of these times, go back to your dashboard and submit a request.
                    <br><em>Aby zarezerwowac sesje, wroc do panelu i wyslij prosbe.</em>
                </p>
            </div>
        `;

        contentEl.innerHTML = html;
    }

    // ── Helpers ────────────────────────────────────────────────────────

    function formatDateISO(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    function showLoading(show) {
        const loadingEl = document.getElementById('calendar-loading');
        const gridEl = document.getElementById('calendar-grid');
        const errorEl = document.getElementById('calendar-error');

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
        const errorEl = document.getElementById('calendar-error');
        errorEl.innerHTML = `<p>${escapeHtml(message)}</p>`;
        errorEl.classList.remove('hidden');
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    // ── Expose Functions Globally ──────────────────────────────────────

    window.onTeacherChange = onTeacherChange;
    window.prevMonth = prevMonth;
    window.nextMonth = nextMonth;
    window.selectDay = selectDay;

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
