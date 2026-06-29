const CACHE_NAME = 'erp-pwa-cache-v1';
const OFFLINE_URL = '/offline/';

const STATIC_ASSETS = [
    '/',
    OFFLINE_URL,
    '/static/css/style.css',
    '/static/js/main.js'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(STATIC_ASSETS);
        })
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});

self.addEventListener('fetch', event => {
    // Only cache GET requests
    if (event.request.method !== 'GET') {
        return;
    }
    
    event.respondWith(
        fetch(event.request)
            .then(response => {
                // If response is valid, clone and cache it
                if (response.status === 200) {
                    let responseClone = response.clone();
                    caches.open(CACHE_NAME).then(cache => {
                        cache.put(event.request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => {
                // Network failed, try to return from cache
                return caches.match(event.request).then(response => {
                    if (response) {
                        return response;
                    }
                    // If not in cache and network fails, return offline page
                    if (event.request.mode === 'navigate') {
                        return caches.match(OFFLINE_URL);
                    }
                });
            })
    );
});
