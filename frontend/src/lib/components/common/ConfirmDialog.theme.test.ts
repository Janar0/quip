import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import ConfirmDialog from './ConfirmDialog.svelte';

describe('ConfirmDialog theme colors', () => {
  afterEach(cleanup);

  it('uses the theme-aware scrim while keeping the dialog surface semantic', () => {
    if (!Element.prototype.animate) {
      Object.defineProperty(Element.prototype, 'animate', {
        configurable: true,
        value: () => ({ cancel() {}, finish() {}, pause() {}, play() {}, reverse() {}, finished: Promise.resolve() }),
      });
    }
    const { container } = render(ConfirmDialog, {
      open: true, title: 'Delete item', confirmLabel: 'Delete', onConfirm: () => {}, onCancel: () => {},
    });

    expect(container.querySelector('.quip-theme-scrim')).toBeTruthy();
    expect(container.querySelector('[role="dialog"].bg-panel')).toBeTruthy();
  });
});
