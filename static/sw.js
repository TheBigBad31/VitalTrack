// static/sw.js - Service Worker VitalTrack PWA
// Cache offline et stratégie réseau pour les données biométriques et nutritionnelles

const CACHE_NAME = 'vitaltrack-cache-v2';
const API_CACHE_NAME = 'vitaltrack-api-v2';
const STATIC_ASSETS = [
  '/',
  '/static/index.html',
  '/static/manifest.json',
  '/static/offline.html',
  '/static/modules/tailwind.min.css',
  '/static/modules/theme.css',
  '/static/vendor/lucide.min.js',
  '/static/vendor/chart.umd.min.js',
  '/static/modules/api.js',
  '/static/modules/lazy.js',
  '/static/modules/dashboard.js',
  '/static/modules/macro_goals.js',
  '/static/modules/nutrition.js',
  '/static/modules/friends.js',
  '/static/modules/views/summary.js',
  '/static/modules/views/weight.js',
  '/static/modules/views/activity.js',
  '/static/modules/views/devices.js',
  '/static/modules/views/goals.js'
];

function isSensitiveApiPath(pathname) {
  return (
    pathname.startsWith('/api/auth/') ||
    /^\/api\/devices\/[^/]+\/token(?:\/|$)/.test(pathname) ||
    pathname.startsWith('/api/backup/')
  );
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME && key !== API_CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'CLEAR_API_CACHE') {
    event.waitUntil(caches.delete(API_CACHE_NAME));
  }
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Pour les requêtes API : ne jamais cacher les endpoints sensibles
  if (url.pathname.startsWith('/api/')) {
    if (isSensitiveApiPath(url.pathname)) {
      event.respondWith(
        fetch(request).catch(() => new Response(
          JSON.stringify({ offline: true, error: 'Connexion réseau indisponible.' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        ))
      );
      return;
    }

    event.respondWith(
      fetch(request)
        .then((response) => {
          if (request.method === 'GET' && response && response.status === 200) {
            const responseClone = response.clone();
            caches.open(API_CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          return caches.open(API_CACHE_NAME).then((cache) => cache.match(request)).then((cachedResponse) => {
            if (cachedResponse) {
              return cachedResponse;
            }
            return new Response(
              JSON.stringify({ offline: true, error: 'Connexion réseau indisponible. Mode hors-ligne actif.' }),
              {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
              }
            );
          });
        })
    );
    return;
  }

  // Pour la navigation HTML : Stratégie Network-First avec fallback index.html puis offline.html
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .catch(() => {
          return caches.match('/static/index.html').then((cachedIndex) => {
            if (cachedIndex) return cachedIndex;
            return caches.match('/static/offline.html');
          });
        })
    );
    return;
  }

  // Pour les fichiers statiques : Stale-While-Revalidate en respectant la query (?v=...)
  event.respondWith(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.match(request).then((cachedResponse) => {
        const networkFetch = fetch(request).then((networkResponse) => {
          if (
            networkResponse &&
            networkResponse.status === 200 &&
            (url.pathname.startsWith('/static/') || url.origin === self.location.origin)
          ) {
            cache.put(request, networkResponse.clone());
          }
          return networkResponse;
        });
        return cachedResponse || networkFetch;
      });
    })
  );
});
