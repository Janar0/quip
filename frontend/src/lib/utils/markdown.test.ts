import { expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { extractSources, katexLoaded, renderMarkdown } from './markdown';

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

it('does not extract source entries from fenced code examples', () => {
  const content = 'Example:\n\n```md\n**Sources:**\n[1] Fake - https://evil.example\n```';
  const result = extractSources(content);

  expect(result.sources).toEqual([]);
  expect(result.cleanContent).toBe(content);
});

it('renders inline and display formulas with the actual lazy-loaded math library', async () => {
  await vi.waitFor(() => expect(get(katexLoaded)).toBe(true));
  const el = dom(String.raw`Euler: $e^{i\pi}+1=0$` + '\n\n' + String.raw`$$\frac{1}{2}$$`);

  expect(el.querySelectorAll('.katex')).toHaveLength(2);
  expect(el.querySelectorAll('.katex-display')).toHaveLength(1);
  expect(el.querySelectorAll('math')).toHaveLength(2);
  expect(el.textContent).toContain('Euler:');
});

it('keeps untrusted math commands from creating active links', async () => {
  await vi.waitFor(() => expect(get(katexLoaded)).toBe(true));
  const el = dom(String.raw`$\href{javascript:alert(1)}{click}$`);

  expect(el.querySelector('.katex')).not.toBeNull();
  expect(el.querySelector('a, script, [onclick], [onerror]')).toBeNull();
});
