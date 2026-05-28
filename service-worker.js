// Velo CRM – Service Worker
// Strategie: Cache-First für App-Shell, Network-First für API-Calls

const CACHE_NAME = 'velo-crm-v2';
const BACKEND_URL = 'https://kundendb.onrender.com';

// App-Shell: diese Dateien werden beim Install gecacht
const SHELL_ASSETS = [
  '/kundendb/',
  '/kundendb/index.html',
  '/kundendb/manifest.json',
  '/kundendb/icons/icon-192.png',
  '/kundendb/icons/icon-512.png',
];

// Offline-Fallback-Seite (wird angezeigt wenn kein Netz + nicht gecacht)
const OFFLINE_PAGE = '/kundendb/offline.html';

// ── Install ──────────────────────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  console.log('[SW] Installing Velo CRM Service Worker...');
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Caching App Shell');
      return cache.addAll(SHELL_ASSETS);
    })
  );
  // Sofort aktivieren (kein Warten auf alte Tabs)
  self.skipWaiting();
});

// ── Activate ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => {
            console.log('[SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      );
    })
  );
  // Sofort alle Clients übernehmen
  self.clients.claim();
});

// ── Fetch ─────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // API-Calls (Backend) → Network-First, kein Caching
  if (url.origin === new URL(BACKEND_URL).origin) {
    event.respondWith(
      fetch(request).catch(() => {
        // Wenn Backend nicht erreichbar: einfache JSON-Fehlermeldung
        return new Response(
          JSON.stringify({
            error: 'offline',
            message: 'Keine Verbindung zum Server. Bitte Netzwerk prüfen.',
          }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          }
        );
      })
    );
    return;
  }

  // Navigationsanfragen (HTML-Seiten) → Cache-First mit Netz-Fallback
  if (request.mode === 'navigate') {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).catch(() =>
          caches.match(OFFLINE_PAGE)
        );
      })
    );
    return;
  }

  // Statische Assets → Cache-First
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        // Nur gültige Responses cachen
        if (!response || response.status !== 200 || response.type === 'opaque') {
          return response;
        }
        const responseToCache = response.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(request, responseToCache);
        });
        return response;
      });
    })
  );
});

// ── Background Sync (optional, für spätere Offline-Aktionen) ─────────────────
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-contacts') {
    console.log('[SW] Background Sync: sync-contacts');
    // Hier könnte man gepufferte Offline-Aktionen absenden
  }
});

console.log('[SW] Service Worker geladen – Velo CRM v1');
