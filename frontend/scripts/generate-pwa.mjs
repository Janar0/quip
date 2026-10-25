import { generateSW } from 'workbox-build';
import { fileURLToPath } from 'node:url';

const build = fileURLToPath(new URL('../build/', import.meta.url));
const { count, size, warnings } = await generateSW({
  globDirectory: build,
  swDest: fileURLToPath(new URL('../build/sw.js', import.meta.url)),
  globPatterns: ['**/*.{js,css,html,svg,png,ico,webp,woff,woff2,webmanifest}'],
  navigateFallback: '/index.html',
  navigateFallbackDenylist: [/^\/api\//],
  cleanupOutdatedCaches: true,
  clientsClaim: true,
  skipWaiting: true,
  runtimeCaching: [
    { urlPattern: ({ url }) => url.pathname.startsWith('/api/'), handler: 'NetworkOnly' },
    {
      urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/,
      handler: 'StaleWhileRevalidate',
      options: {
        cacheName: 'google-fonts-stylesheets',
        expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 }
      }
    },
    {
      urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/,
      handler: 'CacheFirst',
      options: {
        cacheName: 'google-fonts-webfonts',
        expiration: { maxEntries: 30, maxAgeSeconds: 60 * 60 * 24 * 365 },
        cacheableResponse: { statuses: [0, 200] }
      }
    },
    {
      urlPattern: ({ request }) => request.destination === 'image',
      handler: 'CacheFirst',
      options: {
        cacheName: 'images',
        expiration: { maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 * 7 },
        cacheableResponse: { statuses: [0, 200] }
      }
    }
  ]
});

for (const warning of warnings) console.warn(warning);
console.log(`PWA: precached ${count} files (${Math.round(size / 1024)} KiB)`);
