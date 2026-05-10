import '@testing-library/svelte/vitest';
import { vi } from 'vitest';

// Mock svelte-i18n
vi.mock('svelte-i18n', () => ({
  t: {
    subscribe(fn: (v: (key: string) => string) => void) {
      fn((key: string) => key);
      return { unsubscribe: () => {} };
    },
  },
}));

// Provide localStorage mock before any module tries to access it
const _storage: Record<string, string> = {};
(globalThis as any).localStorage = {
  getItem: vi.fn((key: string) => _storage[key] ?? null),
  setItem: vi.fn((key: string, value: string) => { _storage[key] = value; }),
  removeItem: vi.fn((key: string) => { delete _storage[key]; }),
};
