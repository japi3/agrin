/**
 * Service worker for AgriN.
 *
 * What offline means here
 * -----------------------
 * It does not mean the assistant works without a connection -- every answer
 * depends on soil, weather, satellite or a language model, and pretending
 * otherwise would be worse than an honest failure. What it means is:
 *
 *   1. The app itself opens. On a 2G connection in a field, the difference
 *      between a cached shell and a blank white screen is the difference
 *      between a tool someone keeps and one they delete.
 *   2. The last answers a farmer received stay readable. Irrigation advice
 *      is acted on hours after it is read, often at the pump, often where
 *      there is no signal. Losing it because the network dropped is the most
 *      likely moment for this app to fail someone.
 *   3. A question asked with no signal is queued, not lost.
 *
 * Strategy per resource type:
 *   - app shell and assets: cache-first, since they are content-hashed and
 *     change only on deploy
 *   - API reads: network-first with a cache fallback, so a farmer sees fresh
 *     data when online and yesterday's when not -- clearly marked as stale
 *   - API writes: never cached
 */

const VERSION = 'agrin-v1';
const SHELL_CACHE = `${VERSION}-shell`;
const DATA_CACHE = `${VERSION}-data`;

// The minimum needed to render something useful. Hashed assets are added on
// first visit rather than listed here, because their names change per build
// and a stale hardcoded list makes install fail silently.
const SHELL_URLS = ['/', '/manifest.webmanifest', '/icon-192.png'];

// Read-only endpoints worth keeping. Anything that changes state is excluded
// deliberately -- a replayed field creation or a stale cached chat turn is
// worse than an error.
const CACHEABLE_API = [
  '/api/languages',
  '/api/health',
];
const CACHEABLE_API_PREFIX = ['/api/field/'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      // A failed precache must not block activation: the app still works
      // online, and refusing to install would leave the user with nothing.
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)),
      ))
      .then(() => self.clients.claim()),
  );
});

function isCacheableApi(url) {
  if (CACHEABLE_API.includes(url.pathname)) return true;
  return CACHEABLE_API_PREFIX.some((p) => url.pathname.startsWith(p));
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // API reads: fresh when possible, cached when not.
  if (url.pathname.startsWith('/api/')) {
    if (!isCacheableApi(url)) return;
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(DATA_CACHE).then((c) => c.put(request, copy));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          if (!cached) throw new Error('offline and not cached');
          // Mark the response so the interface can say the figures are from
          // the last time there was a signal. Serving stale data silently
          // would let a farmer act on yesterday's forecast believing it is
          // today's.
          const body = await cached.text();
          return new Response(body, {
            status: 200,
            headers: {
              'Content-Type': 'application/json',
              'X-Agrin-Stale': 'true',
            },
          });
        }),
    );
    return;
  }

  // Navigation: serve the cached shell when the network is gone, so the app
  // opens to its own interface rather than the browser's error page.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match('/').then(
        (r) => r || new Response('Offline', { status: 503 }),
      )),
    );
    return;
  }

  // Static assets: cache-first, and fill the cache as they are requested.
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok && response.type === 'basic') {
          const copy = response.clone();
          caches.open(SHELL_CACHE).then((c) => c.put(request, copy));
        }
        return response;
      });
    }),
  );
});
