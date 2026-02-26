/**
 * nav.js — Canonical route mapping and navigation helpers.
 * Ensures all navigation uses .html file paths for static hosting.
 *
 * Load order: api.js → auth.js → state.js → nav.js → page scripts
 */
(function () {
    'use strict';

    var ROUTES = {
        '':             'index.html',
        '/':            'index.html',
        'intake':       'index.html',
        'index':        'index.html',
        'dashboard':           'dashboard.html',
        'student_dashboard':   'student_dashboard.html',
        'assessment':   'assessment.html',
        'games':        'games.html',
        'leaderboard':  'leaderboard.html',
        'profile':      'profile.html',
        'login':        'login.html',
        'register':     'register.html',
        'recall':       'recall.html',
        'session':      'session.html',
        'conversation': 'conversation.html',
        'vocab':        'vocab.html',
    };

    /**
     * Normalize an href to a static-hosting-safe relative path.
     *   "/dashboard"      → "dashboard.html"
     *   "/dashboard.html" → "dashboard.html"
     *   "dashboard.html"  → "dashboard.html" (unchanged)
     *   "/"               → "index.html"
     */
    function normalizeHref(href) {
        if (!href || href === '#' || href.startsWith('http') || href.startsWith('mailto:')) {
            return href;
        }
        // Don't touch API paths
        if (href.indexOf('/api/') === 0 || href.indexOf('api/') === 0) {
            return href;
        }

        // Strip leading "./" or "/"
        var clean = href.replace(/^\.?\//, '');
        // Strip trailing slash
        clean = clean.replace(/\/$/, '');

        // Separate query string
        var qIdx = clean.indexOf('?');
        var path = qIdx >= 0 ? clean.substring(0, qIdx) : clean;
        var query = qIdx >= 0 ? clean.substring(qIdx) : '';

        // Strip .html for lookup
        var key = path.replace(/\.html$/, '');

        if (ROUTES[key]) {
            return ROUTES[key] + query;
        }

        // Already has .html or is a file path (css/, js/, etc.) — return as-is
        return clean;
    }

    /**
     * Navigate to a logical route with optional query params.
     *   routeTo('dashboard')                         → 'dashboard.html'
     *   routeTo('assessment', {student_id: 5})       → 'assessment.html?student_id=5'
     */
    function routeTo(path, params) {
        var href = normalizeHref(path);
        if (params && Object.keys(params).length) {
            var qs = new URLSearchParams(params).toString();
            href += (href.indexOf('?') >= 0 ? '&' : '?') + qs;
        }
        window.location.href = href;
    }

    /**
     * Navigate to the correct dashboard based on user role.
     * If APP.goHomeByRole exists (app.js loaded), use role-based routing.
     * Otherwise fall back to teacher dashboard.
     */
    function goDashboard() {
        if (typeof APP !== 'undefined' && APP.goHomeByRole) {
            APP.goHomeByRole();
            return;
        }
        var studentId = (typeof STATE !== 'undefined') ? STATE.getStudentId() : null;
        if (studentId) {
            routeTo('dashboard', { student_id: studentId });
        } else {
            routeTo('dashboard');
        }
    }

    /**
     * Safety-net: rewrite any remaining root-style <a href="/..."> links.
     * Runs on DOMContentLoaded so it catches links in the initial HTML.
     */
    function wireNavLinks() {
        var links = document.querySelectorAll('a[href]');
        for (var i = 0; i < links.length; i++) {
            var a = links[i];
            var href = a.getAttribute('href');
            if (!href || href === '#' || href.startsWith('http') || href.startsWith('mailto:')) {
                continue;
            }
            if (href.startsWith('/api/')) {
                continue;
            }
            if (href.charAt(0) === '/') {
                a.setAttribute('href', normalizeHref(href));
            }
        }
    }

    /**
     * Dev-mode banner: warn if the page was loaded via a pretty path (no .html).
     */
    function checkPrettyPath() {
        var path = window.location.pathname;
        if (path === '/' || path.endsWith('.html') || path.endsWith('/')) {
            return;
        }
        var banner = document.createElement('div');
        banner.style.cssText =
            'position:fixed;top:0;left:0;right:0;padding:8px 16px;' +
            'background:#fff3cd;color:#856404;border-bottom:2px solid #ffc107;' +
            'z-index:9999;font-size:14px;text-align:center;';
        banner.textContent = 'Warning: URL "' + path + '" will not work under static hosting. ' +
            'Use "' + normalizeHref(path) + '" instead.';
        document.body.prepend(banner);
    }

    // Expose API
    window.NAV = {
        ROUTES: ROUTES,
        normalizeHref: normalizeHref,
        routeTo: routeTo,
        goDashboard: goDashboard,
        wireNavLinks: wireNavLinks,
    };

    // Auto-wire on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            wireNavLinks();
            checkPrettyPath();
        });
    } else {
        wireNavLinks();
        checkPrettyPath();
    }
})();
