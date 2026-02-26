/**
 * state.js — Canonical student identity and error handling for all pages.
 *
 * Load order: api.js → auth.js → state.js → page-specific scripts.
 *
 * Provides:
 *   STATE.getStudentId()      — URL param > localStorage > null
 *   STATE.setStudentId(id)    — persist to localStorage
 *   STATE.requireStudentId()  — returns id or redirects to dashboard
 *   STATE.handleApiError(resp, context) — translates HTTP errors to user messages
 *   STATE.showError(msg)      — persistent red banner
 *   STATE.showSuccess(msg)    — persistent green banner
 *   STATE.showInfo(msg)       — persistent blue banner
 *   STATE.clearStatus()       — hide the banner
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'active_student_id';
    var AUTH_KEY    = 'auth_student_id';
    var REDIRECT_TARGET = 'dashboard.html';

    window.STATE = {

        /**
         * Get the current student ID.
         *  1) ?student_id= in the URL (highest priority)
         *  2) localStorage 'active_student_id'
         *  3) localStorage 'auth_student_id' (set by login/register)
         * Returns a positive integer or null.
         */
        getStudentId: function () {
            // 1) URL query param
            var raw = new URLSearchParams(window.location.search).get('student_id');
            var id = raw ? parseInt(raw, 10) : NaN;
            if (id > 0) {
                // Also persist so other pages can find it
                this.setStudentId(id);
                return id;
            }

            // 2) active_student_id in localStorage
            raw = localStorage.getItem(STORAGE_KEY);
            id = raw ? parseInt(raw, 10) : NaN;
            if (id > 0) return id;

            // 3) auth_student_id (from login/register)
            raw = localStorage.getItem(AUTH_KEY);
            id = raw ? parseInt(raw, 10) : NaN;
            if (id > 0) {
                this.setStudentId(id);
                return id;
            }

            return null;
        },

        /**
         * Persist student ID to localStorage so cross-page navigation works
         * even without query params.
         */
        setStudentId: function (id) {
            var n = parseInt(id, 10);
            if (n > 0) {
                localStorage.setItem(STORAGE_KEY, String(n));
            }
        },

        /**
         * Returns the student ID if available, otherwise redirects to
         * the dashboard with an error message stored in sessionStorage.
         *
         * Usage:
         *   var studentId = STATE.requireStudentId();
         *   if (!studentId) return; // redirect already triggered
         */
        requireStudentId: function () {
            var id = this.getStudentId();
            if (id) return id;

            // Store a message for the target page to show
            sessionStorage.setItem('state_error',
                'No student selected. Please create or select a student first. / Nie wybrano ucznia.');
            // Use role-based redirect if APP is available
            if (typeof APP !== 'undefined' && APP.goHomeByRole) {
                APP.goHomeByRole();
            } else {
                window.location.href = REDIRECT_TARGET;
            }
            return null;
        },

        // ── UI feedback ────────────────────────────────────────────

        /** Ensure the status element exists; create one if needed. */
        _getStatusEl: function () {
            var el = document.getElementById('page-status');
            if (el) return el;

            // Create a status banner at the top of .container
            el = document.createElement('div');
            el.id = 'page-status';
            el.style.cssText =
                'padding:0.75rem 1rem;border-radius:6px;margin-bottom:1rem;font-weight:500;display:none;';
            var container = document.querySelector('.container');
            if (container) {
                // Insert after the first nav or header element
                var nav = container.querySelector('.site-nav');
                if (nav && nav.nextSibling) {
                    container.insertBefore(el, nav.nextSibling);
                } else {
                    container.prepend(el);
                }
            } else {
                document.body.prepend(el);
            }
            return el;
        },

        _setStatus: function (msg, type) {
            var el = this._getStatusEl();
            el.textContent = msg;
            el.style.display = 'block';
            if (type === 'error') {
                el.style.background = '#fdecea';
                el.style.color = '#c0392b';
                el.style.border = '1px solid #f5c6cb';
            } else if (type === 'success') {
                el.style.background = '#e8f5e9';
                el.style.color = '#27ae60';
                el.style.border = '1px solid #c3e6cb';
            } else {
                el.style.background = '#eef6ff';
                el.style.color = '#1a73e8';
                el.style.border = '1px solid #c2deff';
            }
        },

        showError:   function (msg) { this._setStatus(msg, 'error'); },
        showSuccess: function (msg) { this._setStatus(msg, 'success'); },
        showInfo:    function (msg) { this._setStatus(msg, 'info'); },
        clearStatus: function () {
            var el = document.getElementById('page-status');
            if (el) el.style.display = 'none';
        },

        // ── API error translation ──────────────────────────────────

        /**
         * Translate an API error response into an actionable user message.
         * Call after a non-ok response:
         *
         *   if (!resp.ok) {
         *       await STATE.handleApiError(resp, 'loading lessons');
         *       return;
         *   }
         *
         * Returns the parsed error detail string (for callers that need it).
         */
        handleApiError: async function (resp, context) {
            var detail = '';
            try {
                var body = await resp.text();
                var parsed = JSON.parse(body);
                detail = parsed.detail || body.substring(0, 300);
            } catch (_) {
                detail = 'Unexpected response from server';
            }

            var userMsg = '';

            if (resp.status === 401) {
                userMsg = 'Session expired or not logged in. Redirecting to login... / Sesja wygasla.';
                this.showError(userMsg);
                setTimeout(function () { window.location.href = 'login.html'; }, 2000);
                return detail;
            }

            if (resp.status === 404) {
                if (/student not found/i.test(detail)) {
                    userMsg = 'Student not found (ID may be invalid or deleted). ' +
                              'Please select a valid student from the Dashboard. / ' +
                              'Nie znaleziono ucznia. Wybierz ucznia z Panelu.';
                } else if (/assessment not found/i.test(detail)) {
                    userMsg = 'No assessment found. Please start a new assessment. / ' +
                              'Brak testu. Rozpocznij nowy test.';
                } else if (/lesson not found/i.test(detail)) {
                    userMsg = 'Lesson not found. Return to Dashboard. / ' +
                              'Nie znaleziono lekcji. Wroc do Panelu.';
                } else {
                    userMsg = 'Not found: ' + detail;
                }
            } else if (resp.status === 409) {
                userMsg = detail || 'This action was already performed.';
            } else if (resp.status === 422) {
                userMsg = 'Invalid data sent to server: ' + detail;
            } else if (resp.status >= 500) {
                userMsg = 'Server error (' + resp.status + '). Is the backend running at ' +
                          (window.API_BASE || '') + '? / Blad serwera.';
            } else {
                userMsg = (context ? context + ': ' : '') + detail;
            }

            this.showError(userMsg);
            console.error('[STATE] API error (' + resp.status + '):', detail, context || '');
            return detail;
        },

        /**
         * Safe JSON parse for a Response. Returns parsed object or
         * a fallback { detail: ... } on non-JSON body.
         */
        safeJson: async function (resp) {
            var text = await resp.text();
            try {
                return JSON.parse(text);
            } catch (_) {
                return { detail: text.substring(0, 300) || 'Unknown error (non-JSON response)' };
            }
        },

        // ── Init: check for redirect messages ──────────────────────

        init: function () {
            var msg = sessionStorage.getItem('state_error');
            if (msg) {
                sessionStorage.removeItem('state_error');
                this.showError(msg);
            }
        }
    };

    // Auto-init on DOMContentLoaded to show redirect messages
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { STATE.init(); });
    } else {
        STATE.init();
    }
})();
