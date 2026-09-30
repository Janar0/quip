import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import FileAttachment from './FileAttachment.svelte';

describe('FileAttachment theme colors', () => {
  afterEach(cleanup);

  it('keeps the file type and download affordance readable on light surfaces', () => {
    const { container, getByText } = render(FileAttachment, { filename: 'analysis.pdf', chatId: 'chat-1' });
    expect(getByText('Document · PDF').getAttribute('style')).toContain('color: var(--quip-text-muted)');
    expect(container.querySelector('a > div[style*="color: var(--quip-text-muted)"]')).toBeTruthy();
    expect(container.querySelector('a > div[style*="color: var(--quip-text)"]')).toBeTruthy();
  });
});
