/**
 * app.js — Role-based auth helpers for the frontend.
 *
 * Load order: api.js → auth.js → state.js → nav.js → app.js → page scripts
 *
 * Provides:
 *   APP.parseJwt(token)          — decode JWT payload (no verification)
 *   APP.getUserRole()            — extract role from stored JWT ("student"|"teacher")
 *   APP.goHomeByRole()           — redirect to the correct dashboard for the user's role
 *   APP.guardRole(allowed, redir) — redirect away if user's role is not in allowed list
 */
(function () {
    'use strict';

    /**
     * Decode a JWT payload without verification (client-side only).
     * Returns the parsed payload object or null on failure.
     */
    function parseJwt(token) {
        if (!token) return null;
        try {
            var parts = token.split('.');
            if (parts.length !== 3) return null;
            var payload = parts[1];
            // Base64url → Base64
            payload = payload.replace(/-/g, '+').replace(/_/g, '/');
            var json = decodeURIComponent(
                atob(payload)
                    .split('')
                    .map(function (c) {
                        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
                    })
                    .join('')
            );
            return JSON.parse(json);
        } catch (e) {
            console.warn('[app] Failed to parse JWT:', e);
            return null;
        }
    }

    /**
     * Get the current user's role from the stored JWT.
     * Returns "student", "teacher", or null if not logged in.
     */
    function getUserRole() {
        var token = localStorage.getItem('auth_token');
        var payload = parseJwt(token);
        if (!payload) return null;
        return payload.role || 'student';
    }

    /**
     * Navigate to the correct dashboard based on the user's role.
     * Students → student_dashboard.html
     * Teachers → dashboard.html
     */
    function goHomeByRole() {
        var role = getUserRole();
        if (role === 'teacher') {
            window.location.href = 'dashboard.html';
        } else {
            window.location.href = 'student_dashboard.html';
        }
    }

    /**
     * Role guard: redirect if the current user's role is NOT in the allowed list.
     *
     * Usage (at the top of a page script):
     *   APP.guardRole(['teacher'], 'student_dashboard.html');
     *   APP.guardRole(['student'], 'dashboard.html');
     *
     * @param {string[]} allowedRoles - Roles allowed on this page
     * @param {string}   redirectPage - Where to send unauthorized users (wrong role)
     */
    function guardRole(allowedRoles, redirectPage) {
        var role = getUserRole();
        // If not logged in, redirect to login
        if (!role) {
            window.location.href = 'login.html';
            return;
        }
        if (allowedRoles.indexOf(role) === -1) {
            window.location.href = redirectPage || 'login.html';
        }
    }

    /**
     * Render navigation links appropriate for the current user's role.
     * Student: Dashboard, Assessment, Games, Logout
     * Teacher: leaves existing nav unchanged, adds Logout if missing
     * Not logged in: nav left as-is (login/register pages handle themselves)
     */
    function renderNav() {
        var role = getUserRole();
        if (!role) return; // not logged in — don't touch nav

        var navLinks = document.querySelector('.site-nav .nav-links');
        if (!navLinks) return;

        var name = localStorage.getItem('auth_student_name') || '';
        var studentId = localStorage.getItem('auth_student_id') || '';

        if (role === 'student') {
            // Fix nav brand link for students
            var brand = document.querySelector('.site-nav .nav-brand');
            if (brand) brand.setAttribute('href', 'student_dashboard.html');

            var currentPage = window.location.pathname.split('/').pop() || '';
            function activeIf(page) {
                return currentPage === page ? ' class="active"' : '';
            }
            navLinks.innerHTML =
                '<a href="student_dashboard.html"' + activeIf('student_dashboard.html') + '>Dashboard</a>' +
                '<a href="assessment.html' + (studentId ? '?student_id=' + studentId : '') + '"' + activeIf('assessment.html') + '>Assessment</a>' +
                '<a href="games.html' + (studentId ? '?student_id=' + studentId : '') + '"' + activeIf('games.html') + '>Games</a>' +
                '<a href="#" onclick="AUTH.logout();return false;">Logout</a>';
            if (name) {
                var nameEl = document.createElement('span');
                nameEl.className = 'nav-student-name';
                nameEl.textContent = name;
                navLinks.appendChild(nameEl);
            }
        } else {
            // Teacher: just ensure Logout is present
            if (!navLinks.querySelector('[onclick*="logout"]') && !navLinks.textContent.includes('Logout')) {
                var logout = document.createElement('a');
                logout.href = '#';
                logout.textContent = 'Logout';
                logout.onclick = function (e) { e.preventDefault(); AUTH.logout(); };
                navLinks.appendChild(logout);
            }
        }
    }

    /**
     * Server-verified role guard.  Calls /api/auth/me and redirects if the
     * user is on the wrong dashboard.  Only fires on dashboard pages.
     */
    function serverGuardRole() {
        var token = localStorage.getItem('auth_token');
        if (!token) return;
        var page = (window.location.pathname.split('/').pop() || '');
        if (page !== 'dashboard.html' && page !== 'student_dashboard.html') return;

        apiFetch('/api/auth/me').then(function (resp) {
            if (!resp.ok) return null;
            return resp.json();
        }).then(function (user) {
            if (!user) return;
            if (user.role === 'student' && page === 'dashboard.html') {
                window.location.replace('student_dashboard.html');
            } else if (user.role === 'teacher' && page === 'student_dashboard.html') {
                window.location.replace('dashboard.html');
            }
        }).catch(function () {});
    }

    /**
     * For students, rewrite any remaining hardcoded href="dashboard.html"
     * anchors (footers, back-buttons) to point to student_dashboard.html.
     */
    function rewriteDashboardLinks() {
        var role = getUserRole();
        if (role !== 'student') return;
        var links = document.querySelectorAll('a[href="dashboard.html"]');
        for (var i = 0; i < links.length; i++) {
            links[i].setAttribute('href', 'student_dashboard.html');
            // Fix misleading text containing "Teacher"
            if (/teacher/i.test(links[i].textContent)) {
                links[i].textContent = 'Dashboard / Panel';
            }
        }
    }

    // Expose API
    window.APP = {
        parseJwt: parseJwt,
        getUserRole: getUserRole,
        goHomeByRole: goHomeByRole,
        guardRole: guardRole,
        renderNav: renderNav,
        serverGuardRole: serverGuardRole,
    };

    // Auto-render nav + rewrite links on DOMContentLoaded
    function onReady() {
        renderNav();
        rewriteDashboardLinks();
        serverGuardRole();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', onReady);
    } else {
        onReady();
    }
})();
