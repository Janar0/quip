import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ChatInput from './ChatInput.svelte';
import { VoiceSession } from '$lib/services/voice/session';
import { voiceApi } from '$lib/api/voice';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('ends the previous voice session when an active panel changes chat', async () => {
  vi.spyOn(voiceApi, 'config').mockResolvedValue({
    enabled: true, model: 'qwen-audio-3.1-realtime-plus', camera_supported: false,
  });
  vi.spyOn(VoiceSession.prototype, 'start').mockImplementation(async function (this: any) {
    this.options.onState({
      status: 'active', muted: false, cameraSelected: false, cameraEnabled: false,
      cameraError: null, error: null, usage: null, task: null,
    });
  });
  const end = vi.spyOn(VoiceSession.prototype, 'end').mockResolvedValue();
  const onSend = vi.fn();
  const view = render(ChatInput, { props: { chatId: 'chat-A', onSend, variant: 'chat' } });
  await fireEvent.click(screen.getByRole('button', { name: 'voice.open' }));
  await fireEvent.click(screen.getByRole('button', { name: 'voice.start' }));
  await view.rerender({ chatId: 'chat-B', onSend, variant: 'chat' });
  expect(end).toHaveBeenCalledOnce();
});

it('starting an already open voice panel after a chat route change targets the visible chat', async () => {
  vi.spyOn(voiceApi, 'config').mockResolvedValue({
    enabled: true, model: 'qwen-audio-3.1-realtime-plus', camera_supported: false,
  });
  const startedChats: string[] = [];
  vi.spyOn(VoiceSession.prototype, 'start').mockImplementation(async function (this: any) {
    startedChats.push(this.chatId);
  });
  vi.spyOn(VoiceSession.prototype, 'end').mockResolvedValue();
  const onSend = vi.fn();
  const view = render(ChatInput, { props: { chatId: 'chat-A', onSend, variant: 'chat' } });
  await fireEvent.click(screen.getByRole('button', { name: 'voice.open' }));
  await view.rerender({ chatId: 'chat-B', onSend, variant: 'chat' });
  await fireEvent.click(screen.getByRole('button', { name: 'voice.start' }));
  expect(startedChats).toEqual(['chat-B']);
});
