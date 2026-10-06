/* Only the generic offline page and icons are cached. Club data stays online. */
const BASE = new URL(self.registration.scope).pathname.replace(/\/$/, '');
const PREFIX = 'vereinswertung-' + (BASE || 'root') + '-';
const CACHE = PREFIX + 'offline-v2';
const ASSETS = ['/static/offline.html', '/static/offline.css', '/static/icon-192.png', '/static/icon-512.png'].map(path => BASE + path);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith(PREFIX) && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const path = new URL(event.request.url);
  if (event.request.method === 'GET' && path.origin === self.location.origin && ASSETS.includes(path.pathname)) {
    event.respondWith(fetch(event.request).catch(() => caches.match(path.pathname)));
    return;
  }
  if (event.request.mode === 'navigate' && event.request.method === 'GET' && new URL(event.request.url).origin === self.location.origin) {
    event.respondWith(fetch(event.request).catch(() => caches.match(BASE + '/static/offline.html')));
  }
});
