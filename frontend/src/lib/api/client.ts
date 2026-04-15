import { get } from 'svelte/store';
import { authToken } from '$lib/stores/auth';

export async function api(path: string, options: RequestInit = {}): Promise<Response> {
  const token = get(authToken);
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const res = await fetch(path, { ...options, headers });

  if (res.status === 401 && token) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      headers.set('Authorization', `Bearer ${get(authToken)}`);
      return fetch(path, { ...options, headers });
    }
  }

  return res;
}

export async function tryRefresh(): Promise<boolean> {
  const refreshToken = typeof localStorage !== 'undefined' ? localStorage.getItem('refresh_token') : null;
  if (!refreshToken) return false;

  const res = await fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (res.ok) {
    const data = await res.json();
    authToken.set(data.access_token);
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return true;
  }

  authToken.set(null);
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  return false;
}
