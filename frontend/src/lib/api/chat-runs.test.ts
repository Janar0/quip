import { expect, it, vi } from 'vitest';
import { api } from './client';
import { cancelChatRun } from './chat-runs';

vi.mock('./client', () => ({ api: vi.fn() }));

const request = vi.mocked(api);

it('rejects failed cancellation with the actual HTTP status and detail', async () => {
  request.mockResolvedValueOnce(Response.json(
    { detail: 'Run cannot accept cancellation' },
    { status: 409 },
  ));

  await expect(cancelChatRun('chat-1', 'run-1')).rejects.toMatchObject({
    status: 409,
    message: 'Run cannot accept cancellation',
  });
});
