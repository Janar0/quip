import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit(),
		SvelteKitPWA({
			registerType: 'autoUpdate',
			strategies: 'generateSW',
			injectRegister: 'auto',
			devOptions: { enabled: false },
			manifest: {
				name: 'Q.U.I.P.',
				short_name: 'QUIP',
				description: 'Q.U.I.P. — agent-first AI chat',
				theme_color: '#060606',
				background_color: '#060606',
				display: 'standalone',
				orientation: 'portrait',
				start_url: '/',
				scope: '/',
				icons: [
					{ src: '/pwa-192.png', sizes: '192x192', type: 'image/png' },
					{ src: '/pwa-512.png', sizes: '512x512', type: 'image/png' },
					{ src: '/pwa-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
				],
			},
			workbox: {
				globPatterns: ['**/*.{js,css,html,svg,png,ico,webp,woff,woff2}'],
				navigateFallback: '/',
				navigateFallbackDenylist: [/^\/api\//],
				cleanupOutdatedCaches: true,
				clientsClaim: true,
				skipWaiting: true,
				runtimeCaching: [
					{
						urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
						handler: 'NetworkOnly',
					},
					{
						urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/,
						handler: 'StaleWhileRevalidate',
						options: {
							cacheName: 'google-fonts-stylesheets',
							expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 },
						},
					},
					{
						urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/,
						handler: 'CacheFirst',
						options: {
							cacheName: 'google-fonts-webfonts',
							expiration: { maxEntries: 30, maxAgeSeconds: 60 * 60 * 24 * 365 },
							cacheableResponse: { statuses: [0, 200] },
						},
					},
					{
						urlPattern: ({ request }) => request.destination === 'image',
						handler: 'CacheFirst',
						options: {
							cacheName: 'images',
							expiration: { maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 * 7 },
							cacheableResponse: { statuses: [0, 200] },
						},
					},
				],
			},
		}),
	],
	server: {
		// Bind to IPv4 explicitly — on Windows "localhost" resolves to ::1 first,
		// which can stall TCP handshake when the dev server only listens on IPv4.
		host: '127.0.0.1',
		proxy: {
			'/api': {
				target: 'http://127.0.0.1:8000',
				changeOrigin: true,
			},
		},
		warmup: {
			clientFiles: [
				'./src/routes/+layout.svelte',
				'./src/routes/(app)/+layout.svelte',
				'./src/routes/(app)/chat/+page.svelte',
				'./src/routes/(app)/chat/[id]/+page.svelte',
				'./src/lib/components/chat/ChatPane.svelte',
				'./src/lib/components/chat/MessageBubble.svelte',
			],
		},
	},
	build: {
		target: 'esnext',
		minify: 'esbuild',
		rollupOptions: {
			output: {
				manualChunks(id: string) {
					if (id.includes('highlight.js')) return 'vendor-hljs';
					if (id.includes('katex')) return 'vendor-katex';
				},
			},
		},
	},
	esbuild: {
		drop: ['console', 'debugger'],
	},
});
