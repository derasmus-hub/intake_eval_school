(function () {
  const API_BASE = localStorage.getItem("api_base")
    || ("http://" + window.location.hostname + ":8000");
  window.API_BASE = API_BASE;

  // Pages where a 401 should NOT trigger an auto-redirect to login
  var AUTH_PAGES = ['login.html', 'register.html'];
  function isAuthPage() {
    var path = window.location.pathname;
    for (var i = 0; i < AUTH_PAGES.length; i++) {
      if (path.indexOf(AUTH_PAGES[i]) !== -1) return true;
    }
    return false;
  }

  /**
   * Drop-in replacement for fetch() that prepends API_BASE to the path
   * and automatically includes the auth token if available.
   * On 401 (except on login/register pages), clears stored credentials
   * and redirects to login.html.
   * Returns a standard Response object — use exactly like fetch().
   */
  window.apiFetch = function apiFetch(path, options = {}) {
    const url = API_BASE + path;
    const token = localStorage.getItem("auth_token");
    if (token) {
      options.headers = {
        ...options.headers,
        Authorization: "Bearer " + token,
      };
    }
    return fetch(url, options).then(function (resp) {
      if (resp.status === 401 && !isAuthPage()) {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_student_id');
        localStorage.removeItem('auth_student_name');
        localStorage.removeItem('auth_student_email');
        localStorage.removeItem('active_student_id');
        sessionStorage.setItem('state_error',
          'Session expired. Please log in again. / Sesja wygasla. Zaloguj sie ponownie.');
        window.location.href = 'login.html';
      }
      return resp;
    });
  };
})();
