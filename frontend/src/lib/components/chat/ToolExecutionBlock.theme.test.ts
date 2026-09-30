import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import ToolExecutionBlock from './ToolExecutionBlock.svelte';

describe('ToolExecutionBlock theme colors', () => {
  afterEach(cleanup);

  it('uses the semantic error token for error icons and stderr copy', () => {
    const { container } = render(ToolExecutionBlock, {
      execution: {
        id: 'tool-error', name: 'sandbox_execute', status: 'error',
        result: { exit_code: 1, stderr: 'command failed' },
      },
      chatId: 'chat-1',
    });

    expect(container.querySelector('svg[stroke="var(--quip-error)"]')).toBeTruthy();
    expect(container.querySelector('pre[style*="color: var(--quip-error)"]')).toBeTruthy();
  });

  it('uses the semantic success token for successful tool status', () => {
    const { container } = render(ToolExecutionBlock, {
      execution: {
        id: 'tool-ok', name: 'sandbox_execute', status: 'completed', result: { exit_code: 0 },
      },
      chatId: 'chat-1',
    });

    expect(container.querySelector('svg[stroke="var(--quip-success)"]')).toBeTruthy();
  });
});
