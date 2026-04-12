import { writable } from 'svelte/store';

const isMobile = typeof window !== 'undefined' && window.innerWidth < 768;
export const showSidebar = writable<boolean>(!isMobile);

export function toggleSidebar(): void {
  showSidebar.update((v) => !v);
}
