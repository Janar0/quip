import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';
import { relative, sep } from 'node:path';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			alias: { '$lib': 'src/lib' },
			adapter: adapter({ fallback: 'index.html' }),
			compilerOptions: {
				runes: ({ filename }) => {
					const pathSegments = relative(import.meta.dirname, filename).toLowerCase().split(sep);
					return pathSegments.includes('node_modules') ? undefined : true;
				}
			}
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
