import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { tryRefresh } from './client';
import { loadRokiModule, refreshRokiPresence, rokiFetch, rokiPresence } from './roki';

vi.mock('./client', () => ({ tryRefresh: vi.fn() }));
const refresh = vi.mocked(tryRefresh);
const fetchMock = vi.fn();

beforeEach(() => {
  refresh.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  rokiPresence.set('');
});
afterEach(() => vi.unstubAllGlobals());

it('sends the Quip session cookie and keeps the caller content type', async () => {
  fetchMock.mockResolvedValueOnce(new Response('{}'));
  const file = new Blob(['x']);
  await rokiFetch('/api/roki/conversation/attachments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: file,
  });
  const [, init] = fetchMock.mock.calls[0];
  expect(init.credentials).toBe('include');
  expect(init.headers['Content-Type']).toBe('application/octet-stream');
  expect(init.body).toBe(file);
});

it('refreshes an expired session once and retries', async () => {
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
  fetchMock.mockResolvedValueOnce(new Response('{"state":"idle"}'));
  refresh.mockResolvedValueOnce(true);
  const res = await rokiFetch('/api/roki/presence');
  expect(res.status).toBe(200);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it('does not retry when the refresh fails', async () => {
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
  refresh.mockResolvedValueOnce(false);
  expect((await rokiFetch('/api/roki/presence')).status).toBe(401);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('refreshes the session before loading the protected browser module', async () => {
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
  refresh.mockResolvedValueOnce(true);
  await expect(loadRokiModule()).rejects.toThrow();
  expect(refresh).toHaveBeenCalledOnce();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it('shows Roki offline when the service cannot be reached', async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ state: 'working', task: 't' }));
  await refreshRokiPresence();
  expect(get(rokiPresence)).toBe('working');
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));
  await refreshRokiPresence();
  expect(get(rokiPresence)).toBe('offline');
  fetchMock.mockRejectedValueOnce(new TypeError('network'));
  rokiPresence.set('idle');
  await refreshRokiPresence();
  expect(get(rokiPresence)).toBe('offline');
});
