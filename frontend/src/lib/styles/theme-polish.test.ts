import { describe, expect, it } from 'vitest';
// @ts-expect-error Node built-ins are available in Vitest; app dependencies omit @types/node.
import { readFileSync } from 'node:fs';
// @ts-expect-error Node built-ins are available in Vitest; app dependencies omit @types/node.
import { resolve } from 'node:path';
// @ts-expect-error Node built-ins are available in Vitest; app dependencies omit @types/node.
import { cwd } from 'node:process';

const css = [
  readFileSync(resolve(cwd(), 'src/lib/styles/theme.css'), 'utf8'),
  readFileSync(resolve(cwd(), 'src/lib/styles/theme-polish.css'), 'utf8'),
].join('\n');

function token(theme: 'quip-dark' | 'quip-light', name: string): string {
  const blocks = [...css.matchAll(new RegExp(`\\[data-theme=['\"]${theme}['\"]\\]\\s*\\{([^}]+)\\}`, 'g'))];
  const value = blocks.reverse().map((match) => match[1].match(new RegExp(`${name}:\\s*([^;]+);`))?.[1]?.trim()).find(Boolean);
  if (!value) throw new Error(`Missing ${name} in ${theme} theme`);
  return value;
}

function luminance(hex: string): number {
  const channels = hex.slice(1).match(/.{2}/g)!.map((channel) => parseInt(channel, 16) / 255);
  const linear = channels.map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

function contrast(foreground: string, background: string): number {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

describe('theme polish palette', () => {
  it('keeps error and success indicators readable on both theme surfaces', () => {
    expect(contrast(token('quip-light', '--quip-error'), '#f7f7f8')).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token('quip-light', '--quip-success'), '#f7f7f8')).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token('quip-dark', '--quip-error'), '#0a0a0a')).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token('quip-dark', '--quip-success'), '#0a0a0a')).toBeGreaterThanOrEqual(4.5);
  });

  it('defines theme-aware hover, selection, scrim, and error surface colors', () => {
    for (const theme of ['quip-dark', 'quip-light'] as const) {
      expect(token(theme, '--quip-hover-strong')).toBeTruthy();
      expect(token(theme, '--quip-modal-scrim')).toBeTruthy();
      expect(token(theme, '--quip-error-bg')).toBeTruthy();
    }
    expect(css).toMatch(/\.quip-model-menu,\s*\.quip-export-menu[\s\S]*?background:\s*var\(--quip-bg\)/);
    expect(css).toContain('.quip-model-search:focus-within');
  });
});
