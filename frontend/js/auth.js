/**
 * Shared auth utilities for all pages.
 * Include this script before page-specific scripts.
 */

const AUTH = {
    getToken() {
        return localStorage.getItem('auth_token');
    },

    getStudentId() {
        return localStorage.getItem('auth_student_id');
    },

    getStudentName() {
        return localStorage.getItem('auth_student_name');
    },

    isLoggedIn() {
        return !!this.getToken();
    },

    logout() {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_student_id');
        localStorage.removeItem('auth_student_name');
        localStorage.removeItem('auth_student_email');
        localStorage.removeItem('active_student_id');
        window.location.href = 'login.html';
    },

    // Wrapper for fetch that includes auth header and API_BASE
    async apiFetch(url, options = {}) {
        const token = this.getToken();
        if (token) {
            options.headers = {
                ...options.headers,
                'Authorization': 'Bearer ' + token,
            };
        }
        const base = (typeof API_BASE !== 'undefined') ? API_BASE : '';
        return fetch(base + url, options);
    },

    // Update nav bar with auth state
    updateNav() {
        const navStudentEl = document.getElementById('nav-student-name');
        if (!navStudentEl) return;

        if (this.isLoggedIn()) {
            const name = this.getStudentName() || '';
            navStudentEl.innerHTML = `<strong>${name}</strong> | <a href="#" onclick="AUTH.logout();return false;" style="color:rgba(255,255,255,0.8);">Logout</a>`;
        }
    },

    // Add auth links to nav if not logged in
    addAuthLinks() {
        const navLinks = document.querySelector('.site-nav .nav-links');
        if (!navLinks) return;

        if (this.isLoggedIn()) {
            // Add logout link
            const link = document.createElement('a');
            link.href = '#';
            link.textContent = 'Logout';
            link.onclick = (e) => { e.preventDefault(); AUTH.logout(); };
            navLinks.appendChild(link);
        } else {
            // Add login/register links
            const login = document.createElement('a');
            login.href = 'login.html';
            login.textContent = 'Login';
            navLinks.appendChild(login);

            const reg = document.createElement('a');
            reg.href = 'register.html';
            reg.textContent = 'Register';
            navLinks.appendChild(reg);
        }
    },
};
