import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, it, vi } from 'vitest';
import DeepResearchProgress from './DeepResearchProgress.svelte';

it('keeps Stop retryable while a research cancellation is pending', async () => {
  const onStop = vi.fn();
  render(DeepResearchProgress, {
    props: {
      history: [],
      current: { phase: 'searching' },
      status: 'cancelling',
      onStop,
    },
  });

  const stopButton = screen.getByRole('button', { name: 'research.stopRequested' });
  expect((stopButton as HTMLButtonElement).disabled).toBe(false);
  await fireEvent.click(stopButton);
  expect(onStop).toHaveBeenCalledOnce();
});
