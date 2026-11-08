/* 60Online service worker — offline fallback + cache-first for static assets ONLY.
   Never caches API responses or page HTML (pages may be personalised/authenticated). */
const VERSION = "v1";
const STATIC_CACHE = `60online-static-${VERSION}`;
const OFFLINE_URL = "/offline";
const PRECACHE = [OFFLINE_URL, "/brand/60online-app-icon.png", "/icon.svg"];
const STATIC_RE = /^\/(_next\/static\/|brand\/|images\/)|\.(?:css|js|woff2?|png|jpe?g|webp|avif|svg|ico)$/i;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("60online-") && k !== STATIC_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // network only, never cached

  if (req.mode === "navigate") {
    // HTML: always network; offline → the static offline page (cached at install, public content).
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL).then((r) => r || Response.error())));
    return;
  }

  if (STATIC_RE.test(url.pathname) && !req.headers.has("authorization")) {
    event.respondWith(
      caches.open(STATIC_CACHE).then((cache) =>
        cache.match(req).then((hit) => hit || fetch(req).then((res) => {
          if (res.ok && res.type === "basic") cache.put(req, res.clone());
          return res;
        })),
      ),
    );
  }
});
