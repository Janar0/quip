import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  branchSelections,
  persistBranchSelections,
  restoreBranchSelections,
  clearBranchSelections,
} from './chat.ts';
import { get } from 'svelte/store';

const _storage: Record<string, string> = {};
(globalThis as any).localStorage = {
  getItem: vi.fn((key: string) => _storage[key] ?? null),
  setItem: vi.fn((key: string, value: string) => { _storage[key] = value; }),
  removeItem: vi.fn((key: string) => { delete _storage[key]; }),
};

vi.stubGlobal('localStorage', (globalThis as any).localStorage);

describe('branch persistence', () => {
  const CHAT_ID = 'chat-test-123';

  beforeEach(() => {
    branchSelections.set({});
    Object.keys(_storage).forEach((k) => delete _storage[k]);
    vi.mocked(localStorage.removeItem).mockClear();
    vi.mocked(localStorage.setItem).mockClear();
    vi.mocked(localStorage.getItem).mockReturnValue(null);
  });

  it('saves selections to localStorage', () => {
    branchSelections.set({ parent_1: 'child_a', parent_2: 'child_b' });
    persistBranchSelections(CHAT_ID);

    expect(localStorage.setItem).toHaveBeenCalledOnce();
    const [key, value] = vi.mocked(localStorage.setItem).mock.calls[0] as [string, string];
    expect(key).toBe(`quip_branches_${CHAT_ID}`);
    expect(JSON.parse(value)).toEqual({ parent_1: 'child_a', parent_2: 'child_b' });
  });

  it('restores selections from localStorage', () => {
    const stored = JSON.stringify({ root: 'msg-2' });
    vi.mocked(localStorage.getItem).mockReturnValue(stored);
    restoreBranchSelections(CHAT_ID);
    expect(get(branchSelections)).toEqual({ root: 'msg-2' });
  });

  it('clears selections for a chat', () => {
    clearBranchSelections(CHAT_ID);
    expect(localStorage.removeItem).toHaveBeenCalledWith(`quip_branches_${CHAT_ID}`);
  });

  it('does not crash on invalid stored JSON', () => {
    vi.mocked(localStorage.getItem).mockReturnValue('not-json');
    restoreBranchSelections(CHAT_ID);
    expect(get(branchSelections)).toEqual({});
  });
});
