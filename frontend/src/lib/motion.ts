import { cubicOut, backOut } from 'svelte/easing';

export const D1 = 120;
export const D2 = 220;
export const D3 = 380;

export const easeOut = cubicOut;
export const easeSpring = backOut;

export function prm(duration: number): number {
  if (typeof window === 'undefined') return duration;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : duration;
}
