import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		proxy: {
			'/api': {
				target: 'http://localhost:8000',
				changeOrigin: true,
			},
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
