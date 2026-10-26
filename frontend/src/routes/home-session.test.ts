import { cleanup, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { addMessages, init } from 'svelte-i18n';
import { goto } from '$app/navigation';
import { fetchMe } from '$lib/api/auth';
import { authLoading, currentUser } from '$lib/stores/auth';
import english from '$lib/i18n/locales/en.json';
import HomePage from './+page.svelte';

vi.unmock('svelte-i18n');
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const user = {
  id: 'persisted-user', email: 'pwa@example.test', username: 'pwa',
  name: 'PWA User', role: 'user', profile_image_url: null,
};

beforeEach(async () => {
  vi.mocked(goto).mockReset();
  currentUser.set(null);
  authLoading.set(true);
  addMessages('en', english);
  await init({ fallbackLocale: 'en', initialLocale: 'en' });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('PWA launch at the home route', () => {
  it('waits for cookie session restoration before offering sign in', async () => {
    render(HomePage);
    expect(screen.queryByRole('link', { name: english['auth.login'] })).toBeNull();
    expect(goto).not.toHaveBeenCalled();

    authLoading.set(false);
    expect(await screen.findByRole('link', { name: english['auth.login'] })).toBeTruthy();
  });

  it.each([false, true])('opens chat after restoring a persisted session (access expired: %s)', async (expired) => {
    let accessValid = !expired;
    let refreshCount = 0;
    vi.stubGlobal('fetch', vi.fn(async (path: string, options?: RequestInit) => {
      expect(options?.credentials).toBe('include');
      if (path === '/api/auth/me') {
        return Response.json(accessValid ? user : { detail: 'Not authenticated' }, { status: accessValid ? 200 : 401 });
      }
      if (path === '/api/auth/refresh') {
        expect(options?.method).toBe('POST');
        expect(options?.body).toBe('{}');
        refreshCount++;
        accessValid = true;
        return Response.json({ status: 'ok' });
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
    render(HomePage);

    // The root layout resolves HttpOnly cookies through fetchMe on every launch.
    expect(await fetchMe()).toBe(true);
    authLoading.set(false);

    await waitFor(() => expect(goto).toHaveBeenCalledWith('/chat', { replaceState: true }));
    expect(get(currentUser)).toEqual(user);
    expect(refreshCount).toBe(expired ? 1 : 0);
    expect(screen.queryByRole('link', { name: english['auth.login'] })).toBeNull();
  });

  it('keeps the public landing page when the refresh session has expired', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_path: string, options?: RequestInit) => {
      expect(options?.credentials).toBe('include');
      return Response.json({ detail: 'Invalid session' }, { status: 401 });
    }));
    render(HomePage);
    expect(await fetchMe()).toBe(false);
    authLoading.set(false);

    expect(await screen.findByRole('link', { name: english['auth.login'] })).toBeTruthy();
    expect(get(currentUser)).toBeNull();
    expect(goto).not.toHaveBeenCalled();
  });
});
