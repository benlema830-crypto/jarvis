/* The Jarvis phone app's service worker (served as /sw.js by phone_bridge.py).
   It keeps a copy of the page so the app opens even when the PC can't be reached, and shows the alerts
   Jarvis sends (phone_push.py). It never stores messages or the phone key. */
'use strict';
const SHELL = 'jarvis-shell-v1';

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL).then(cache => cache.addAll(['/', '/phone-icon-192.png'])));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(key => key !== SHELL).map(key => caches.delete(key))))
    .then(() => self.clients.claim()));
});

// The page itself: the newest copy when the PC answers, the saved one when it doesn't.
self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).then(response => {
    if (response.ok) { const copy = response.clone(); caches.open(SHELL).then(cache => cache.put('/', copy)); }
    return response;
  }).catch(() => caches.match('/')));
});

// iOS cancels the alerts of an app whose push arrives without a notification shown, so every push shows one.
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch {}
  event.waitUntil(self.registration.showNotification(data.title || 'Jarvis', {
    body: data.body || 'Open Jarvis to see what is new.',
    tag: data.tag || 'jarvis',
    icon: '/phone-icon-192.png',
    data: { kind: data.kind || 'message' },
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windows => {
    for (const win of windows) if ('focus' in win) return win.focus();
    return self.clients.openWindow('/');
  }));
});
