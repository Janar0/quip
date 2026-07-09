import { writable } from 'svelte/store';

export type DrawerKind = 'artifacts' | 'research' | 'files';

export const activeDrawer = writable<DrawerKind | null>(null);

export function openDrawer(kind: DrawerKind): void {
  activeDrawer.set(kind);
}

export function closeDrawer(): void {
  activeDrawer.set(null);
}
