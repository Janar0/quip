import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const __dirname = dirname(fileURLToPath(import.meta.url));
const staticDir = resolve(__dirname, '..', 'static');

const iconSvg = ({ size, safe = 1 }) => {
	const rectInset = ((1 - safe) / 2) * size;
	const rectSize = size - rectInset * 2;
	const radius = rectSize * 0.23;
	const fontSize = Math.round(rectSize * 0.56);
	const cx = size / 2;
	const cy = size / 2;
	return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#fafafa"/>
      <stop offset="1" stop-color="#d4d4d8"/>
    </linearGradient>
  </defs>
  <rect width="${size}" height="${size}" fill="#060606"/>
  <rect x="${rectInset}" y="${rectInset}" width="${rectSize}" height="${rectSize}" rx="${radius}" fill="url(#g)"/>
  <text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="central"
        font-family="-apple-system, 'Segoe UI', Manrope, Arial, sans-serif"
        font-weight="800" font-size="${fontSize}" fill="#0a0a0a"
        letter-spacing="-${fontSize * 0.04}">Q</text>
</svg>`;
};

const targets = [
	{ file: 'pwa-192.png', size: 192, safe: 1 },
	{ file: 'pwa-512.png', size: 512, safe: 1 },
	{ file: 'pwa-maskable-512.png', size: 512, safe: 0.7 },
	{ file: 'apple-touch-icon.png', size: 180, safe: 1 },
];

await mkdir(staticDir, { recursive: true });

for (const { file, size, safe } of targets) {
	const svg = iconSvg({ size, safe });
	const out = resolve(staticDir, file);
	await sharp(Buffer.from(svg)).png().toFile(out);
	console.log(`wrote ${file}`);
}
