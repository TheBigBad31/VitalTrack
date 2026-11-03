// static/sw.js - Service Worker VitalTrack PWA
// Cache offline et stratégie réseau pour les données biométriques et nutritionnelles

const CACHE_NAME = 'vitaltrack-cache-v1';
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
  '/static/modules/nutrition.js',
  '/static/modules/friends.js'
];

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
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Pour les requêtes API : Stratégie Network-First
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (request.method === 'GET' && response && response.status === 200) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          return caches.match(request).then((cachedResponse) => {
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

  // Pour les fichiers statiques (scripts, styles, polices, images) : Cache-First
  event.respondWith(
    caches.match(request, { ignoreSearch: true }).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(request).then((networkResponse) => {
        if (
          networkResponse &&
          networkResponse.status === 200 &&
          (url.pathname.startsWith('/static/') || url.origin === self.location.origin)
        ) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, responseToCache);
          });
        }
        return networkResponse;
      });
    })
  );
});
