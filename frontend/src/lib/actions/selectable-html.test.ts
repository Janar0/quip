import { afterEach, expect, it } from 'vitest';
import { selectableHtml } from './selectable-html';

afterEach(() => { document.getSelection()?.removeAllRanges(); document.body.innerHTML = ''; });

it('preserves selected text while streaming and catches up after deselection', () => {
  const node = document.createElement('div');
  document.body.append(node);
  const action = selectableHtml(node, '<p>Original answer</p>');
  const original = node.firstChild;
  const range = document.createRange();
  range.selectNodeContents(node);
  document.getSelection()?.addRange(range);
  action.update('<p>Original answer with new tokens</p>');
  expect(node.firstChild).toBe(original);
  expect(document.getSelection()?.toString()).toBe('Original answer');
  document.getSelection()?.removeAllRanges();
  document.dispatchEvent(new Event('selectionchange'));
  expect(node.textContent).toBe('Original answer with new tokens');
  action.destroy();
});
