import { writable } from 'svelte/store';

export type ThemeName = 'dark' | 'light' | 'gray';

const STORAGE_KEY = 'quip_theme';

function getInitialTheme(): ThemeName {
  if (typeof window === 'undefined') return 'gray';
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'dark' || stored === 'light' || stored === 'gray') return stored;
  return 'gray';
}

export const theme = writable<ThemeName>(getInitialTheme());

export function setTheme(t: ThemeName): void {
  theme.set(t);
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_KEY, t);
  document.documentElement.dataset.theme = `quip-${t}`;
  if (t === 'light') {
    document.documentElement.classList.remove('dark');
  } else {
    document.documentElement.classList.add('dark');
  }
}
