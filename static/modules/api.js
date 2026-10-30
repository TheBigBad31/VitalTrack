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

/**
 * Rendu des icônes Lucide limité à un conteneur (Lot 2 - BALI-90).
 * lucide.createIcons() parcourt tout le document et reconstruit chaque <svg> :
 * on neutralise temporairement les icônes situées hors du conteneur pour ne
 * traiter que celles qui viennent d'être injectées. Sans conteneur, on conserve
 * le comportement global historique.
 * @param {Element} [root] - Conteneur dont les icônes doivent être (re)rendues.
 */
function refreshIcons(root) {
  if (!window.lucide || typeof lucide.createIcons !== 'function') return;

  if (!root || typeof root.querySelectorAll !== 'function') {
    try { lucide.createIcons(); } catch (e) {}
    return;
  }

  const DEFERRED_ATTR = 'data-lucide-deferred';
  const pending = root.querySelectorAll('[data-lucide]');
  if (pending.length === 0) return;

  const deferred = [];
  try {
    document.querySelectorAll('[data-lucide]').forEach((el) => {
      if (root.contains(el)) return;
      const name = el.getAttribute('data-lucide');
      deferred.push([el, name]);
      el.removeAttribute('data-lucide');
      el.setAttribute(DEFERRED_ATTR, name);
    });
    lucide.createIcons();
  } catch (err) {
    console.warn('[icons] Rendu Lucide ciblé impossible, repli global :', err);
    try { lucide.createIcons(); } catch (e) {}
  } finally {
    deferred.forEach(([el, name]) => {
      if (!el || !el.isConnected) return;
      el.removeAttribute(DEFERRED_ATTR);
      el.setAttribute('data-lucide', name);
    });
  }
}

window.refreshIcons = refreshIcons;
