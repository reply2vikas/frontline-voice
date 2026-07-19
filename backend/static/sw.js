/* Service worker for Frontline Voice.
 *
 * A volunteer works in a crowded concourse where signal is unreliable, so the
 * shell must survive a dropped connection. The strategy is deliberately split:
 *
 *   - the app shell (HTML, CSS, JS, icons) is cache-first, because those assets
 *     only change when a new version ships;
 *   - every /api/ request is network-first, because operational state that is
 *     minutes old is worse than no answer at all. A stale gate status could send
 *     people toward a closed entrance.
 *
 * CACHE_VERSION is bumped on every release. Older caches are deleted during
 * activation so a returning volunteer never runs a mixed set of assets.
 */

const CACHE_VERSION = "frontline-v1";
const SHELL = [
  "/",
  "/static/app.css",
  "/static/app.js",
  "/static/favicon.svg",
  "/static/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Operational data must never be served stale.
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(request).catch(() => caches.match(request)));
    return;
  }

  // Shell assets: serve from cache, refresh in the background.
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    }),
  );
});
