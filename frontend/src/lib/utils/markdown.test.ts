import { expect, it } from 'vitest';
import { extractSources, renderMarkdown } from './markdown';

function dom(markdown: string) {
  const el = document.createElement('div');
  el.innerHTML = renderMarkdown(markdown);
  return el;
}

it('escapes malicious code language labels and raw HTML', () => {
  const el = dom('```<img/src=x/onerror=alert(1)>\ncode\n```\n<script>alert(1)</script>');
  expect(el.querySelector('img, script, [onerror]')).toBeNull();
});

it('renders formatted link text without allowing javascript links', () => {
  const el = dom('[**Visible** label](https://example.com)\n[bad](javascript:alert)');
  expect(el.querySelector('a strong')?.textContent).toBe('Visible');
  expect(el.querySelectorAll('a')).toHaveLength(1);
});

it('does not replace array indices or URL attributes with citation markup', () => {
  const el = dom('`items[1]`\n\n```js\nitems[2]\n```\n\n[link](https://example.com/items[1])');
  expect(el.querySelector('code')?.textContent).toBe('items[1]');
  expect(el.querySelector('pre code')?.textContent).toContain('items[2]');
  expect(el.querySelector('a')?.getAttribute('href')).toContain('items[1]');
});

it('preserves text following a loose sources section', () => {
  const result = extractSources('Answer\nSources:\nSource https://example.com\n\nImportant conclusion');
  expect(result.cleanContent).toContain('Important conclusion');
});
