// static/modules/api.js - Centralized API client for VitalTrack
// Handles JWT authentication, automatic token injection, 401 interception and unified HTTP requests.

const JWT_STORAGE_KEY = 'vitaltrack_jwt_token';
const REFRESH_TOKEN_STORAGE_KEY = 'vitaltrack_refresh_token';
const GOOGLE_SESSION_KEY = 'vitaltrack_google_session';
const OFFLINE_QUEUE_DB = 'vitaltrack_offline_queue';
const OFFLINE_QUEUE_STORE = 'mutations';

let _refreshInFlight = null;

function isAuthRefreshBypassUrl(url) {
  const str = String(url || '');
  return /\/api\/auth\/(refresh|login|register|google|logout)(\?|$)/.test(str)
    || /\/api\/(login|register)(\?|$)/.test(str);
}

/**
 * Rafraîchit automatiquement l'access token via POST /api/auth/refresh (avec déduplication single-flight).
 * Retourne le nouvel access token en cas de succès, ou null sinon.
 * @returns {Promise<string|null>}
 */
async function refreshAccessToken() {
  if (_refreshInFlight) {
    return _refreshInFlight;
  }
  const refreshToken = typeof localStorage !== 'undefined'
    ? localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY)
    : null;
  if (!refreshToken) {
    return null;
  }

  _refreshInFlight = (async () => {
    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken })
      });
      if (!res || !res.ok) {
        return null;
      }
      const data = await res.json();
      if (data && data.access_token) {
        if (typeof localStorage !== 'undefined') {
          localStorage.setItem(JWT_STORAGE_KEY, data.access_token);
          if (data.refresh_token) {
            localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, data.refresh_token);
          }
        }
        return data.access_token;
      }
      return null;
    } catch (_) {
      return null;
    } finally {
      _refreshInFlight = null;
    }
  })();

  return _refreshInFlight;
}

function clearSessionAfterAuthFailure() {
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem(JWT_STORAGE_KEY);
    localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
    localStorage.removeItem(GOOGLE_SESSION_KEY);
  }
  if (typeof currentUnifiedSession !== 'undefined') {
    currentUnifiedSession = { is_authenticated: false };
  }
  if (typeof renderUnifiedAuthState === 'function') {
    renderUnifiedAuthState(
      (typeof currentUnifiedSession !== 'undefined' && currentUnifiedSession) || { is_authenticated: false },
      null
    );
  }
  if (typeof openAuthModal === 'function') {
    openAuthModal();
  }
}

function isQueueableOfflineMutation(url, method) {
  if (String(method || 'GET').toUpperCase() !== 'POST') return false;
  return /\/api\/meals\/journal\/[^/]+\/items/.test(url) || /\/api\/weights(\?|$)/.test(url);
}

function openOfflineQueueDB() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB non disponible'));
      return;
    }
    const req = indexedDB.open(OFFLINE_QUEUE_DB, 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(OFFLINE_QUEUE_STORE)) {
        db.createObjectStore(OFFLINE_QUEUE_STORE, { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function enqueueOfflineMutation(url, opts) {
  const db = await openOfflineQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readwrite');
    tx.objectStore(OFFLINE_QUEUE_STORE).add({
      url,
      method: opts.method || 'POST',
      headers: opts.headers || {},
      body: opts.body || null,
      createdAt: new Date().toISOString()
    });
    tx.oncomplete = () => {
      refreshOfflineQueueBadge();
      resolve();
    };
    tx.onerror = () => reject(tx.error);
  });
}

async function getOfflineQueue() {
  const db = await openOfflineQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readonly');
    const req = tx.objectStore(OFFLINE_QUEUE_STORE).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

async function removeOfflineMutation(id) {
  const db = await openOfflineQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readwrite');
    tx.objectStore(OFFLINE_QUEUE_STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function refreshOfflineQueueBadge(isSyncing = false) {
  const badge = document.getElementById('offline-queue-badge');
  const textEl = document.getElementById('offline-queue-badge-text');
  if (!badge || !textEl) return;
  let count = 0;
  try {
    const items = await getOfflineQueue();
    count = items.length;
  } catch (_) {
    count = 0;
  }
  const isOffline = typeof navigator !== 'undefined' && navigator.onLine === false;
  if (isSyncing) {
    badge.classList.remove('hidden');
    badge.classList.add('flex');
    textEl.textContent = `Sync (${count})...`;
  } else if (isOffline || count > 0) {
    badge.classList.remove('hidden');
    badge.classList.add('flex');
    textEl.textContent = count > 0 ? `Hors-ligne (${count} en attente)` : 'Hors-ligne';
  } else {
    badge.classList.add('hidden');
    badge.classList.remove('flex');
  }
}

async function flushOfflineQueue() {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
  let items = [];
  try {
    items = await getOfflineQueue();
  } catch (_) {
    return;
  }
  if (!items.length) {
    refreshOfflineQueueBadge(false);
    return;
  }
  await refreshOfflineQueueBadge(true);
  for (const item of items) {
    try {
      const headers = Object.assign({ 'Content-Type': 'application/json' }, item.headers || {});
      const currentToken = typeof localStorage !== 'undefined' ? localStorage.getItem(JWT_STORAGE_KEY) : null;
      if (currentToken) {
        headers['Authorization'] = `Bearer ${currentToken}`;
      }
      let res = await fetch(item.url, {
        method: item.method || 'POST',
        headers,
        body: item.body
      });
      if (res.status === 401) {
        const refreshedToken = await refreshAccessToken();
        if (refreshedToken) {
          headers['Authorization'] = `Bearer ${refreshedToken}`;
          res = await fetch(item.url, {
            method: item.method || 'POST',
            headers,
            body: item.body
          });
        }
      }
      if (res.status === 401) {
        clearSessionAfterAuthFailure();
        break;
      }
      if (res.ok || (res.status >= 400 && res.status < 500)) {
        await removeOfflineMutation(item.id);
      }
    } catch (_) {
      break;
    }
  }
  await refreshOfflineQueueBadge(false);
  if (typeof loadDashboardData === 'function') {
    loadDashboardData();
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    flushOfflineQueue();
  });
  window.addEventListener('offline', () => {
    refreshOfflineQueueBadge(false);
  });
  window.addEventListener('DOMContentLoaded', () => {
    refreshOfflineQueueBadge(false);
    if (navigator.onLine) {
      flushOfflineQueue();
    }
  });
  window.VitalTrackOfflineQueue = {
    enqueueOfflineMutation,
    getOfflineQueue,
    flushOfflineQueue,
    refreshOfflineQueueBadge
  };
}

/**
 * Main HTTP wrapper injecting Bearer token and handling global auth errors.
 * Shows global loading bar at start, hides it when request completes.
 * @param {string} url - API endpoint
 * @param {RequestInit} [options={}] - fetch options
 * @returns {Promise<Response>}
 */
async function apiFetch(url, options = {}) {
  if (typeof window !== 'undefined' && typeof window.showGlobalLoading === 'function') {
    window.showGlobalLoading(true);
  }
  const opts = Object.assign({}, options);
  opts.headers = Object.assign({}, opts.headers || {});

  const token = typeof localStorage !== 'undefined' ? localStorage.getItem(JWT_STORAGE_KEY) : null;
  if (token && !opts.headers['Authorization']) {
    opts.headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    let response = await fetch(url, opts);
    if (response.status === 503 && isQueueableOfflineMutation(url, opts.method)) {
      await enqueueOfflineMutation(url, opts);
      return new Response(
        JSON.stringify({ queued: true, offline: true, message: 'Enregistré hors-ligne, synchronisation automatique au retour du réseau.' }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    }
    if (response.status === 401 && !isAuthRefreshBypassUrl(url)) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        const retryOpts = Object.assign({}, opts, {
          headers: Object.assign({}, opts.headers, { Authorization: `Bearer ${newToken}` })
        });
        response = await fetch(url, retryOpts);
      }
      if (response.status === 401) {
        console.warn(`[apiFetch 401] Session expirée ou non autorisée sur ${url}. Réinitialisation session.`);
        clearSessionAfterAuthFailure();
      }
    }
    return response;
  } catch (err) {
    if (isQueueableOfflineMutation(url, opts.method)) {
      await enqueueOfflineMutation(url, opts);
      return new Response(
        JSON.stringify({ queued: true, offline: true, message: 'Enregistré hors-ligne, synchronisation automatique au retour du réseau.' }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    }
    throw err;
  } finally {
    if (typeof window !== 'undefined' && typeof window.showGlobalLoading === 'function') {
      window.showGlobalLoading(false);
    }
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
if (typeof window !== 'undefined') {
  window.apiFetch = apiFetch;
  window.API = API;
  window.refreshAccessToken = refreshAccessToken;
  window.JWT_STORAGE_KEY = JWT_STORAGE_KEY;
  window.REFRESH_TOKEN_STORAGE_KEY = REFRESH_TOKEN_STORAGE_KEY;
  window.GOOGLE_SESSION_KEY = GOOGLE_SESSION_KEY;
}

/**
 * Nettoyage et échappement sécurisé des chaînes pour injection HTML/attributs (Anti-XSS).
 * @param {*} str - Valeur à échapper
 * @returns {string} - Chaîne échappée sans caractères HTML dangereux
 */
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Validation et assainissement d'URL pour attributs src / href (Anti-javascript:).
 * Autorise http, https, data:image/, blob: et chemins relatifs /.
 * @param {string} url - URL candidate
 * @returns {string} - URL safe ou chaîne vide si suspecte
 */
function sanitizeUrl(url) {
  if (!url || typeof url !== 'string') return '';
  const trimmed = url.trim();
  if (/^(?:https?:\/\/|\/|blob:|data:image\/(?:png|jpeg|webp|gif);base64,)/i.test(trimmed)) {
    return escapeHtml(trimmed);
  }
  return '';
}

window.escapeHtml = escapeHtml;
window.sanitizeUrl = sanitizeUrl;
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    apiFetch,
    API,
    refreshAccessToken,
    JWT_STORAGE_KEY,
    REFRESH_TOKEN_STORAGE_KEY,
    GOOGLE_SESSION_KEY,
    refreshIcons,
    escapeHtml,
    sanitizeUrl
  };
}

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
