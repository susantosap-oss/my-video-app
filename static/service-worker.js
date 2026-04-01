const CACHE_NAME = "vidgen-v1";
const STATIC_ASSETS = [
  "/",
  "/login",
  "/static/manifest.json",
];

// Install: cache static shell
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: clear old caches
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch strategy:
// - API calls (/api/*): network-only (never cache)
// - Static assets: network-first, fallback to cache
// - Upload/download/render: network-only
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);

  // Always network for API, uploads, downloads, render
  if (url.pathname.startsWith("/api/") ||
      url.pathname.startsWith("/uploads/") ||
      url.pathname.startsWith("/output/")) {
    return; // default browser fetch
  }

  // Network-first for everything else
  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Cache successful GET responses for static assets
        if (event.request.method === "GET" && response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
