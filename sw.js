// Offline support: app shell + program + exercise photos are cached on install.
// Bump VERSION when shell files change so clients pick up the new cache.
const VERSION = "v1";
const CACHE = `challenge100-${VERSION}`;
const SHELL = ["./", "index.html", "data.json", "manifest.webmanifest",
  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png"];
const NETWORK_TIMEOUT_MS = 3000;
const FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL);
    const data = await (await cache.match("data.json")).json();
    const images = [...new Set(Object.values(data.moves).flatMap(m => m.images || []))];
    await cache.addAll(images);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k.startsWith("challenge100-") && k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
    const clients = await self.clients.matchAll({ type: "window" });
    clients.forEach(c => c.postMessage({ type: "offline-ready", version: VERSION }));
  })());
});

// Program and page: try network briefly (fresh data), fall back to cache.
async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await Promise.race([
      fetch(request),
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), NETWORK_TIMEOUT_MS)),
    ]);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch (err) {
    const cached = await cache.match(request, { ignoreSearch: true });
    if (cached) return cached;
    throw err;
  }
}

// Photos, icons, fonts: cache first, fill the cache on first network hit.
async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request, { ignoreSearch: true });
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok || response.type === "opaque") await cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", event => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (FONT_HOSTS.includes(url.hostname)) { event.respondWith(cacheFirst(request)); return; }
  if (url.origin !== self.location.origin) return;
  const fresh = request.mode === "navigate" || url.pathname.endsWith("/data.json") || url.pathname.endsWith("/index.html");
  event.respondWith(fresh ? networkFirst(request) : cacheFirst(request));
});
