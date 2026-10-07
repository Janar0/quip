import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';

// Verify the generated worker rather than assuming the Vite settings agree
// with adapter-static's output. No browser or network is needed.
const build = new URL('../build/', import.meta.url);
const origin = 'https://quip.invalid/';
let precache = [];
let navigation;
class Strategy {}
class NavigationRoute {
  constructor(handler, options) { navigation = { handler, ...options }; }
}
const workbox = {
  clientsClaim() {}, cleanupOutdatedCaches() {}, registerRoute() {},
  precacheAndRoute(entries) { precache = entries; },
  createHandlerBoundToURL(url) { return url; },
  NavigationRoute,
  NetworkOnly: Strategy, StaleWhileRevalidate: Strategy, CacheFirst: Strategy,
  ExpirationPlugin: Strategy, CacheableResponsePlugin: Strategy,
};
const define = (_dependencies, factory) => factory(workbox);
runInNewContext(readFileSync(new URL('sw.js', build), 'utf8'), {
  self: { define, skipWaiting() {} }, define,
}, { timeout: 1000 });

assert.ok(navigation, 'Generated worker must have a navigation route');
const fallback = new URL(navigation.handler, origin);
assert.ok(precache.some(entry => new URL(entry.url, origin).href === fallback.href),
  `Navigation fallback ${fallback.pathname} is missing from the precache`);
const filename = fallback.pathname === '/' ? 'index.html' : fallback.pathname.slice(1);
assert.ok(existsSync(fileURLToPath(new URL(filename, build))),
  `Navigation fallback ${filename} is missing from the static build`);
assert.ok(navigation.denylist.some(pattern => pattern.test('/api/auth/me')),
  'API requests must bypass the cached application shell');
console.log('PWA: cached navigation shell exists; API requests bypass it');
