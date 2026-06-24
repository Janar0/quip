import { defineConfig } from 'vitest/config';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = resolve(fileURLToPath(import.meta.url), '..');

export default defineConfig({
	// NOTE: sveltekit() already bundles vite-plugin-svelte. A second standalone
	// svelte() plugin double-compiles .svelte/.svelte.js modules — the second
	// pass chokes on `import * as $` and throws a CompileError, which broke
	// every test (incl. @testing-library's props.svelte.js).
	plugins: [
		tailwindcss(),
		sveltekit(),
	],
	resolve: {
		alias: {
			$lib: resolve(__dirname, './src/lib'),
			$app: resolve(__dirname, './.svelte-kit/runtime/app'),
		},
		conditions: ['browser'],
	},
	test: {
		environment: 'jsdom',
		include: ['src/**/*.{test,spec}.{ts,svelte}'],
		globals: true,
		setupFiles: ['./vitest-setup.ts'],
	},
});
