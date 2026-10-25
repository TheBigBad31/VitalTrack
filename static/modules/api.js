// static/modules/api.js - Centralized API client for VitalTrack
// Handles JWT authentication, automatic token injection, 401 interception and unified HTTP requests.

const JWT_STORAGE_KEY = 'vitaltrack_jwt_token';
const GOOGLE_SESSION_KEY = 'vitaltrack_google_session';

try {
  localStorage.removeItem('vitaltrack_backup_cache');
} catch (e) {}

/**
 * Main HTTP wrapper injecting Bearer token and handling global auth errors.
 * @param {string} url - API endpoint
 * @param {RequestInit} [options={}] - fetch options
 * @returns {Promise<Response>}
 */
async function apiFetch(url, options = {}) {
  const opts = Object.assign({}, options);
  opts.headers = Object.assign({}, opts.headers || {});

  const token = localStorage.getItem(JWT_STORAGE_KEY);
  if (token && !opts.headers['Authorization']) {
    opts.headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(url, opts);
    if (response.status === 401) {
      console.warn(`[apiFetch 401] Session expirée ou non autorisée sur ${url}. Réinitialisation session.`);
      localStorage.removeItem(JWT_STORAGE_KEY);
      localStorage.removeItem(GOOGLE_SESSION_KEY);
      if (typeof currentUnifiedSession !== 'undefined') {
        currentUnifiedSession = { is_authenticated: false };
      }
      if (typeof renderUnifiedAuthState === 'function') {
        renderUnifiedAuthState(currentUnifiedSession || { is_authenticated: false }, null);
      }
      if (typeof openAuthModal === 'function') {
        openAuthModal();
      }
    }
    return response;
  } catch (err) {
    throw err;
  }
}

// Global API helper methods
const API = {
  get: (url, opts = {}) => apiFetch(url, { ...opts, method: 'GET' }),
  post: (url, data, opts = {}) => apiFetch(url, {
    ...opts,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    body: JSON.stringify(data)
  }),
  put: (url, data, opts = {}) => apiFetch(url, {
    ...opts,
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    body: JSON.stringify(data)
  }),
  delete: (url, opts = {}) => apiFetch(url, { ...opts, method: 'DELETE' })
};

// Make apiFetch and API globally accessible
window.apiFetch = apiFetch;
window.API = API;
window.JWT_STORAGE_KEY = JWT_STORAGE_KEY;
window.GOOGLE_SESSION_KEY = GOOGLE_SESSION_KEY;
