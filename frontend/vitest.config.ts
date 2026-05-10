import { defineConfig } from 'vitest/config';
import { sveltekit } from '@sveltejs/kit/vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = resolve(fileURLToPath(import.meta.url), '..');

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit(),
		svelte({ compilerOptions: { generate: 'client' } }),
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
