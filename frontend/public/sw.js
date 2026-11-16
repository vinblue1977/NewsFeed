/* Offline access: the app shell, the last stories and the pictures are kept on the phone.
 *
 * - Pages and /data/*.json: the network first (up to 4 s, so a weak signal does not hang), then the last copy kept.
 * - /assets/* (content-hashed, never change) and story pictures: the kept copy first.
 * - /api/*, the private watch-/earn- files and anything that is not a same-origin GET: never touched.
 * Bump VERSION to drop every kept copy. */
const VERSION = 'v1';
const PAGES = `news-pages-${VERSION}`;
const DATA = `news-data-${VERSION}`;
const ASSETS = `news-assets-${VERSION}`;
const IMAGES = `news-images-${VERSION}`;
const KEEP = [PAGES, DATA, ASSETS, IMAGES];
const NETWORK_WAIT_MS = 4000;
const MAX_ASSETS = 40;  // old builds' files are trimmed away
const MAX_IMAGES = 200;

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => !KEEP.includes(n)).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

async function trim(name, max) {
  const cache = await caches.open(name);
  const keys = await cache.keys();
  if (keys.length > max) await Promise.all(keys.slice(0, keys.length - max).map((k) => cache.delete(k)));  // oldest first
}

/** Keeps a copy in the background: it never delays the response. */
function keep(event, name, key, response, max) {
  if (!response.ok) return;
  event.waitUntil(
    caches.open(name).then((cache) => cache.put(key, response)).then(() => (max ? trim(name, max) : undefined)).catch(() => undefined),
  );
}

/** The network first; the kept copy if it fails or is slower than NETWORK_WAIT_MS. With no kept copy the network gets as
 * long as it needs. */
async function networkFirst(event, name, key = event.request) {
  const kept = await caches.match(key, { cacheName: name });
  const controller = new AbortController();
  const timer = kept ? setTimeout(() => controller.abort(), NETWORK_WAIT_MS) : undefined;
  try {
    const response = await fetch(event.request, { signal: controller.signal });
    clearTimeout(timer);
    if (response.ok) keep(event, name, key, response.clone());
    else if (kept) return kept;  // a server error must not hide the last good copy
    return response;
  } catch (error) {
    clearTimeout(timer);
    if (kept) return kept;
    throw error;
  }
}

async function cacheFirst(event, name, max) {
  const kept = await caches.match(event.request, { cacheName: name });
  if (kept) return kept;
  const response = await fetch(event.request);
  keep(event, name, event.request, response.clone(), max);
  return response;
}

/** The private watchlist quotes and earnings are named after a hash of the secret key: never kept on the device. */
const PRIVATE = /^\/data\/(watch|earn)-/;

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  const path = url.pathname;
  if (path.startsWith('/api/') || PRIVATE.test(path)) return;
  if (path.startsWith('/assets/')) event.respondWith(cacheFirst(event, ASSETS, MAX_ASSETS));
  else if (path.startsWith('/data/img/')) event.respondWith(cacheFirst(event, IMAGES, MAX_IMAGES));
  else if (path.startsWith('/data/')) event.respondWith(networkFirst(event, DATA));
  else if (request.mode === 'navigate') event.respondWith(networkFirst(event, PAGES, '/index.html'));
});
