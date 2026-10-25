import { writable } from 'svelte/store';
import { tryRefresh } from '$lib/api/client';

/**
 * Roki is a separate service with its own repository. Quip only proxies
 * /api/roki/* and loads Roki's own UI module from there, so Roki fixes ship
 * without rebuilding Quip.
 */
export const ROKI_API = '/api/roki';
const MODULE_URL = `${ROKI_API}/ui/module/roki-module.js`;

export type RokiState =
  | ''
  | 'offline'
  | 'blocked_storage'
  | 'idle'
  | 'waiting'
  | 'queued'
  | 'working'
  | 'sleeping'
  | 'paused';

export const rokiEnabled = writable(false);
export const rokiPresence = writable<RokiState>('');

/** Session-aware fetch for the module: Quip cookie, shared refresh, no forced JSON type. */
export async function rokiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const request: RequestInit = { ...init, credentials: 'include' };
  const res = await fetch(url, request);
  if (res.status === 401 && (await tryRefresh())) return fetch(url, request);
  return res;
}

let moduleLoad: Promise<unknown> | null = null;

export function loadRokiModule(): Promise<unknown> {
  moduleLoad ??= import(/* @vite-ignore */ MODULE_URL).catch((error) => {
    moduleLoad = null;
    throw error;
  });
  return moduleLoad;
}

/** Mount a Roki element (roki-room / roki-admin) into a host node. */
export async function mountRoki(
  host: HTMLElement,
  tag: 'roki-room' | 'roki-admin',
  props: Record<string, unknown> = {},
): Promise<HTMLElement> {
  await loadRokiModule();
  const element = document.createElement(tag);
  element.setAttribute('api', ROKI_API);
  Object.assign(element, { fetcher: rokiFetch, ...props });
  host.replaceChildren(element);
  return element;
}

export async function refreshRokiPresence(): Promise<void> {
  try {
    const res = await rokiFetch(`${ROKI_API}/presence`);
    if (res.ok) rokiPresence.set(((await res.json()).state ?? '') as RokiState);
    else rokiPresence.set('offline');
  } catch {
    rokiPresence.set('offline');
  }
}
