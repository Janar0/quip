import { writable } from 'svelte/store';

export type ThemeName = 'dark' | 'light';

const STORAGE_KEY = 'quip_theme';

function getInitialTheme(): ThemeName {
  if (typeof window === 'undefined') return 'dark';
  let stored: string | null = null;
  try { stored = localStorage.getItem(STORAGE_KEY); } catch { /* Storage may be disabled. */ }
  if (stored === 'dark' || stored === 'light') return stored;
  return 'dark';
}

export const theme = writable<ThemeName>(getInitialTheme());

export function setTheme(t: ThemeName): void {
  theme.set(t);
  if (typeof window === 'undefined') return;
  try { localStorage.setItem(STORAGE_KEY, t); } catch { /* Theme still works for this session. */ }
  document.documentElement.style.background = '';
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', t === 'light' ? '#ececee' : '#060606');
  document.documentElement.dataset.theme = `quip-${t}`;
  if (t === 'light') {
    document.documentElement.classList.remove('dark');
  } else {
    document.documentElement.classList.add('dark');
  }
}
