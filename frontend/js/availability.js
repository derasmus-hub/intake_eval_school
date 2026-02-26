/**
 * availability.js — Teacher availability management UI
 *
 * Handles:
 *   - Weekly schedule CRUD (day + time windows)
 *   - Date overrides (mark specific dates as unavailable)
 *   - Preview of upcoming availability
 */
(function () {
    'use strict';

    const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
    const DAY_LABELS = {
        monday: 'Monday / Poniedzialek',
        tuesday: 'Tuesday / Wtorek',
        wednesday: 'Wednesday / Sroda',
        thursday: 'Thursday / Czwartek',
        friday: 'Friday / Piatek',
        saturday: 'Saturday / Sobota',
        sunday: 'Sunday / Niedziela'
    };

    // Current state
    let weeklyWindows = {}; // { monday: [{start_time, end_time}, ...], ... }
    let overrides = []; // [{ date, is_available, reason }, ...]

    // ── Initialization ─────────────────────────────────────────────────

    function init() {
        // Set min date for override picker to today
        const today = new Date().toISOString().split('T')[0];
        const dateInput = document.getElementById('override-date');
        if (dateInput) dateInput.min = today;

        // Initialize weekly windows structure
        DAYS.forEach(day => { weeklyWindows[day] = []; });

        // Load existing data
        loadAvailability();
    }

    // ── API Calls ──────────────────────────────────────────────────────

    async function loadAvailability() {
        try {
            const resp = await apiFetch('/api/teacher/availability');
            if (!resp.ok) {
                showStatus('weekly-status', 'Error loading availability', 'error');
                return;
            }
            const data = await resp.json();

            // Parse weekly windows
            DAYS.forEach(day => { weeklyWindows[day] = []; });
            (data.windows || []).forEach(w => {
                const day = w.day_of_week.toLowerCase();
                if (weeklyWindows[day]) {
                    weeklyWindows[day].push({
                        start_time: w.start_time,
                        end_time: w.end_time
                    });
                }
            });

            // Parse overrides (only unavailable ones for display)
            overrides = (data.overrides || []).filter(o => !o.is_available);

            // Render UI
            renderWeeklySchedule();
            renderOverridesList();
            renderPreview();

        } catch (err) {
            console.error('[availability] Load error:', err);
            showStatus('weekly-status', 'Error: ' + err.message, 'error');
        }
    }

    async function saveWeeklySchedule() {
        const btn = document.getElementById('save-weekly-btn');
        btn.disabled = true;
        btn.textContent = 'Saving...';

        try {
            // Collect all windows from current state
            const windows = [];
            DAYS.forEach(day => {
                weeklyWindows[day].forEach(w => {
                    windows.push({
                        day_of_week: day,
                        start_time: w.start_time,
                        end_time: w.end_time
                    });
                });
            });

            const resp = await apiFetch('/api/teacher/availability', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ windows })
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                showStatus('weekly-status', 'Error: ' + (err.detail || 'Could not save'), 'error');
                return;
            }

            showStatus('weekly-status', 'Weekly schedule saved! / Harmonogram zapisany!', 'success');
            renderPreview();

        } catch (err) {
            showStatus('weekly-status', 'Error: ' + err.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Save Weekly Schedule / Zapisz harmonogram';
        }
    }

    async function addOverride() {
        const dateInput = document.getElementById('override-date');
        const reasonInput = document.getElementById('override-reason');
        const date = dateInput.value;
        const reason = reasonInput.value.trim();

        if (!date) {
            showStatus('override-status', 'Please select a date / Wybierz date', 'error');
            return;
        }

        try {
            const resp = await apiFetch('/api/teacher/availability/overrides', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    date: date,
                    is_available: false,
                    reason: reason || null
                })
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                showStatus('override-status', 'Error: ' + (err.detail || 'Could not save'), 'error');
                return;
            }

            // Add to local state
            overrides.push({ date, is_available: false, reason });
            overrides.sort((a, b) => a.date.localeCompare(b.date));

            // Clear inputs
            dateInput.value = '';
            reasonInput.value = '';

            showStatus('override-status', 'Date marked as unavailable / Data oznaczona jako niedostepna', 'success');
            renderOverridesList();
            renderPreview();

        } catch (err) {
            showStatus('override-status', 'Error: ' + err.message, 'error');
        }
    }

    async function removeOverride(date) {
        if (!confirm('Remove this override? / Usunac ten wyjatek?')) return;

        try {
            const resp = await apiFetch('/api/teacher/availability/overrides?date=' + encodeURIComponent(date), {
                method: 'DELETE'
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                alert('Error: ' + (err.detail || 'Could not delete'));
                return;
            }

            // Remove from local state
            overrides = overrides.filter(o => o.date !== date);

            renderOverridesList();
            renderPreview();

        } catch (err) {
            alert('Error: ' + err.message);
        }
    }

    // ── Rendering ──────────────────────────────────────────────────────

    function renderWeeklySchedule() {
        const container = document.getElementById('weekly-schedule');
        if (!container) return;

        let html = '<div class="weekly-grid">';

        DAYS.forEach(day => {
            const windows = weeklyWindows[day] || [];
            html += `
                <div class="day-card" data-day="${day}">
                    <div class="day-header">
                        <span class="day-name">${DAY_LABELS[day]}</span>
                        <button class="btn-add-window" onclick="addWindow('${day}')" title="Add time window">+</button>
                    </div>
                    <div class="day-windows" id="windows-${day}">
                        ${windows.length === 0
                            ? '<p class="no-windows">No hours set / Brak godzin</p>'
                            : windows.map((w, i) => renderWindowRow(day, w, i)).join('')
                        }
                    </div>
                </div>
            `;
        });

        html += '</div>';
        container.innerHTML = html;
    }

    function renderWindowRow(day, window, index) {
        return `
            <div class="window-row">
                <input type="time" value="${window.start_time}"
                       onchange="updateWindow('${day}', ${index}, 'start_time', this.value)">
                <span class="window-to">to</span>
                <input type="time" value="${window.end_time}"
                       onchange="updateWindow('${day}', ${index}, 'end_time', this.value)">
                <button class="btn-remove-window" onclick="removeWindow('${day}', ${index})" title="Remove">&times;</button>
            </div>
        `;
    }

    function renderOverridesList() {
        const container = document.getElementById('overrides-list');
        if (!container) return;

        if (overrides.length === 0) {
            container.innerHTML = '<p class="meta">No date overrides set. / Brak wyjatkow.</p>';
            return;
        }

        const today = new Date().toISOString().split('T')[0];
        const futureOverrides = overrides.filter(o => o.date >= today);

        if (futureOverrides.length === 0) {
            container.innerHTML = '<p class="meta">No upcoming overrides. / Brak nadchodzacych wyjatkow.</p>';
            return;
        }

        let html = '<div class="overrides-grid">';
        futureOverrides.forEach(o => {
            const dateObj = new Date(o.date + 'T00:00:00');
            const dateStr = dateObj.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
            html += `
                <div class="override-card">
                    <div class="override-info">
                        <span class="override-date">${dateStr}</span>
                        ${o.reason ? `<span class="override-reason">${escapeHtml(o.reason)}</span>` : ''}
                    </div>
                    <button class="btn-remove-override" onclick="removeOverride('${o.date}')" title="Remove">&times;</button>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    function renderPreview() {
        const container = document.getElementById('availability-preview');
        if (!container) return;

        // Generate next 14 days
        const days = [];
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        for (let i = 0; i < 14; i++) {
            const date = new Date(today);
            date.setDate(today.getDate() + i);
            days.push(date);
        }

        // Build override lookup
        const overrideLookup = {};
        overrides.forEach(o => { overrideLookup[o.date] = o; });

        let html = '<div class="preview-grid">';
        days.forEach(date => {
            const dateStr = date.toISOString().split('T')[0];
            const dayName = DAYS[date.getDay() === 0 ? 6 : date.getDay() - 1]; // JS Sunday=0
            const windows = weeklyWindows[dayName] || [];
            const override = overrideLookup[dateStr];

            let status = 'available';
            let windowsDisplay = '';

            if (override && !override.is_available) {
                status = 'unavailable';
                windowsDisplay = 'Unavailable';
            } else if (windows.length === 0) {
                status = 'no-hours';
                windowsDisplay = 'No hours';
            } else {
                windowsDisplay = windows.map(w => `${w.start_time}-${w.end_time}`).join(', ');
            }

            const dayLabel = date.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
            const isToday = dateStr === today.toISOString().split('T')[0];

            html += `
                <div class="preview-day preview-${status}${isToday ? ' preview-today' : ''}">
                    <span class="preview-date">${dayLabel}</span>
                    <span class="preview-windows">${windowsDisplay}</span>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    }

    // ── Window Management (local state) ────────────────────────────────

    function addWindow(day) {
        weeklyWindows[day].push({ start_time: '09:00', end_time: '12:00' });
        renderWeeklySchedule();
    }

    function updateWindow(day, index, field, value) {
        if (weeklyWindows[day] && weeklyWindows[day][index]) {
            weeklyWindows[day][index][field] = value;
        }
    }

    function removeWindow(day, index) {
        weeklyWindows[day].splice(index, 1);
        renderWeeklySchedule();
    }

    // ── Helpers ────────────────────────────────────────────────────────

    function showStatus(elementId, message, type) {
        const el = document.getElementById(elementId);
        if (!el) return;

        el.textContent = message;
        el.className = 'status-message status-' + type;
        el.style.display = 'block';

        // Auto-hide after 5 seconds
        setTimeout(() => {
            el.style.display = 'none';
        }, 5000);
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    // ── Expose Functions Globally ──────────────────────────────────────

    window.saveWeeklySchedule = saveWeeklySchedule;
    window.addOverride = addOverride;
    window.removeOverride = removeOverride;
    window.addWindow = addWindow;
    window.updateWindow = updateWindow;
    window.removeWindow = removeWindow;

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
