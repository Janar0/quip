import { currentUser } from '$lib/stores/auth';
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
  bootstrap_token?: string;
}

export interface SetupStatus {
  required: boolean;
  admin_email_configured: boolean;
}

export async function getSetupStatus(): Promise<SetupStatus> {
  const response = await fetch('/api/auth/setup', { credentials: 'include' });
  if (!response.ok) return { required: false, admin_email_configured: false };
  return response.json();
}

export async function login(data: LoginData): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }));
    return { ok: false, error: err.detail };
  }

  if (!(await fetchMe())) return { ok: false, error: 'Account pending approval' };
  return { ok: true };
}

export async function register(data: RegisterData): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Registration failed' }));
    return { ok: false, error: err.detail };
  }

  if (!(await fetchMe())) return { ok: false, error: 'Account created and pending approval' };
  return { ok: true };
}

export async function fetchMe(): Promise<boolean> {
  const res = await api('/api/auth/me');
  if (res.ok) {
    currentUser.set(await res.json());
    return true;
  } else if (res.status === 401 || res.status === 403) {
    currentUser.set(null);
  }
  return false;
}

export async function logout(): Promise<void> {
  try {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
  } finally {
    currentUser.set(null);
  }
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
