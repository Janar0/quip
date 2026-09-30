import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import VoiceCallPanel from './VoiceCallPanel.svelte';
import ChatInput from './ChatInput.svelte';
import { voiceApi } from '$lib/api/voice';
import { VoiceSession, type VoiceSessionState } from '$lib/services/voice/session';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('VoiceCallPanel', () => {
  it('opens the voice panel from an existing chat without requesting media permission', async () => {
    const getUserMedia = vi.fn();
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    render(ChatInput, {
      props: { chatId: 'chat-1', onSend: vi.fn(), variant: 'chat' },
    });

    await fireEvent.click(screen.getByRole('button', { name: 'voice.open' }));

    expect(screen.getByRole('region', { name: 'voice.panelTitle' })).toBeTruthy();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('does not request microphone or camera before the explicit call action', async () => {
    vi.spyOn(voiceApi, 'config').mockResolvedValue({
      enabled: true, model: 'qwen-audio-3.1-realtime-plus', camera_supported: true,
    });
    const getUserMedia = vi.fn();
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    render(VoiceCallPanel, { props: { chatId: 'chat-1', onClose: vi.fn() } });

    expect(screen.getByText('voice.costNotice')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('button', { name: 'voice.chooseCamera' })).toBeTruthy());
    await fireEvent.click(screen.getByRole('button', { name: 'voice.chooseCamera' }));
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'voice.cameraSelected' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('hides camera selection when the configured Qwen Audio model is audio-only', async () => {
    vi.spyOn(voiceApi, 'config').mockResolvedValue({
      enabled: false, model: 'qwen-audio-3.1-realtime-plus', camera_supported: false,
    });
    const getUserMedia = vi.fn();
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    render(VoiceCallPanel, { props: { chatId: 'chat-1', onClose: vi.fn() } });

    await waitFor(() => expect(screen.getByText('voice.cameraModelUnsupported')).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'voice.chooseCamera' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'voice.cameraSelected' })).toBeNull();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('requests microphone only after Start and shows a recoverable permission error', async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new DOMException('Permission denied', 'NotAllowedError'));
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });
    render(VoiceCallPanel, { props: { chatId: 'chat-1', onClose: vi.fn() } });

    expect(getUserMedia).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: 'voice.start' }));

    await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith({ audio: true, video: false }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('voice.error.microphone_permission_denied'));
  });

  it('shows a delegated task and separates steering and explicit cancellation from call controls', async () => {
    const task: NonNullable<VoiceSessionState['task']> = {
      taskId: 'task-1', status: 'running', revision: 1, contextVersion: 1,
      content: '', progress: 'Round 1 of 5', error: null,
    };
    const start = vi.spyOn(VoiceSession.prototype, 'start').mockImplementation(async function (this: any) {
      this.options.onState({
        status: 'active', muted: false, cameraSelected: false, cameraEnabled: false,
        cameraError: null, error: null, usage: null, task,
      });
    });
    const steerTask = vi.spyOn(VoiceSession.prototype, 'steerTask').mockResolvedValue();
    const cancelTask = vi.spyOn(VoiceSession.prototype, 'cancelTask').mockResolvedValue();
    render(VoiceCallPanel, { props: { chatId: 'chat-1', onClose: vi.fn() } });

    await fireEvent.click(screen.getByRole('button', { name: 'voice.start' }));
    const panel = screen.getByRole('region', { name: 'voice.panelTitle' });
    await waitFor(() => expect(panel.textContent).toContain('voice.task.status.running'));
    expect(screen.getByText('Round 1 of 5')).toBeTruthy();

    const clarification = screen.getByRole('textbox', { name: 'voice.task.clarification' });
    await fireEvent.input(clarification, { target: { value: 'Добавь официальные источники' } });
    await fireEvent.click(screen.getByRole('button', { name: 'voice.task.sendSteering' }));
    expect(steerTask).toHaveBeenCalledWith('Добавь официальные источники');

    await fireEvent.click(screen.getByRole('button', { name: 'voice.task.cancel' }));
    expect(cancelTask).toHaveBeenCalledOnce();
    expect(start).toHaveBeenCalledOnce();
  });
});
