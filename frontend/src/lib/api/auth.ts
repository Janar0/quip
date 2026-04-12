import { authToken, currentUser } from '$lib/stores/auth';
import { api } from '$lib/api/client';

export interface LoginData {
  email: string;
  password: string;
}

export interface RegisterData {
  email: string;
  username: string;
  name: string;
  password: string;
}

export async function login(data: LoginData): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }));
    return { ok: false, error: err.detail };
  }

  const tokens = await res.json();
  authToken.set(tokens.access_token);
  localStorage.setItem('access_token', tokens.access_token);
  localStorage.setItem('refresh_token', tokens.refresh_token);

  await fetchMe();
  return { ok: true };
}

export async function register(data: RegisterData): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Registration failed' }));
    return { ok: false, error: err.detail };
  }

  const tokens = await res.json();
  authToken.set(tokens.access_token);
  localStorage.setItem('access_token', tokens.access_token);
  localStorage.setItem('refresh_token', tokens.refresh_token);

  await fetchMe();
  return { ok: true };
}

export async function fetchMe(): Promise<void> {
  const res = await api('/api/auth/me');
  if (res.ok) {
    currentUser.set(await res.json());
  }
}

export function logout(): void {
  authToken.set(null);
  currentUser.set(null);
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
}

export async function getUserSettings(): Promise<Record<string, string>> {
  const res = await api('/api/auth/settings');
  if (res.ok) return res.json();
  return {};
}

export async function updateUserSettings(data: Record<string, string>): Promise<boolean> {
  const res = await api('/api/auth/settings', {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
  return res.ok;
}
