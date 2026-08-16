// Self-destructing service worker.
//
// This fork serves individual files directly from src/ and relies on ?v=
// cache-busters for updates. The old worker here was cache-first with
// ignoreSearch:true — it served a stale app shell forever and defeated the
// versioning, which is why edits "never showed up" across reloads.
//
// This worker caches NOTHING and intercepts NOTHING (no fetch handler =
// pure network passthrough). On activation it deletes every leftover cache.
// index.html additionally unregisters any service worker on load, so a
// stale worker cannot persist on this origin.
self.addEventListener( 'install', function () {
	self.skipWaiting();
});

self.addEventListener( 'activate', function ( event ) {
	event.waitUntil(( async function () {
		const keys = await caches.keys();
		await Promise.all( keys.map( function ( key ) {
			return caches.delete( key );
		}));
		await self.clients.claim();
	})());
});
