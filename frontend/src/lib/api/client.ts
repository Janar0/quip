import { currentUser } from '$lib/stores/auth';

// Prevent concurrent refresh attempts — all 401s share one in-flight refresh.
let refreshPromise: Promise<boolean> | null = null;

export async function api(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const request = { ...options, headers, credentials: 'include' as const };
  const res = await fetch(path, request);

  const canRefresh = !['/api/auth/login', '/api/auth/register', '/api/auth/refresh', '/api/auth/logout'].includes(path);
  if (res.status === 401 && canRefresh) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return fetch(path, request);
    }
  }

  return res;
}

export async function tryRefresh(): Promise<boolean> {
  // Deduplicate: if a refresh is already in flight, reuse it.
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: '{}',
      });

      if (res.ok) {
        return true;
      }

      // Only clear tokens when the session is genuinely dead (401/403).
      // Transient failures (500/502/503, 429, etc.) must NOT log the user
      // out — a brief backend hiccup during refresh would otherwise kick
      // every active user to the login screen.
      if (res.status === 401 || res.status === 403) {
        currentUser.set(null);
      }
      return false;
    } catch {
      // Network error — don't clear tokens, just report failure.
      // The caller (api() or silent refresh) decides what to do with the 401.
      return false;
    }
  })();

  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

export async function apiJson<T>(path: string, fallback: T, options: RequestInit = {}): Promise<T> {
  const res = await api(path, options);
  if (res.ok) return res.json() as Promise<T>;
  return fallback;
}

export async function apiOk(path: string, method: string, body?: unknown): Promise<boolean> {
  const init: RequestInit = { method };
  if (body !== undefined) init.body = JSON.stringify(body);
  const res = await api(path, init);
  return res.ok;
}
