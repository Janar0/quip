import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import SourcesList from './SourcesList.svelte';
import { extractSources, renderMarkdown } from '$lib/utils/markdown';

afterEach(cleanup);

function base64UrlUtf8(value: string): string {
  const bytes = new TextEncoder().encode(value);
  const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('');
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

describe('retrieved source footer rendering', () => {
  it('keeps the validated result URL authoritative when a title contains Markdown and HTML', () => {
    const title = '[click](https://evil.example) <img src=x onerror=alert(1)> \\ **bold**';
    const encodedTitle = base64UrlUtf8(title);
    const footer = [
      'Answer [1].',
      '',
      '---',
      '**Sources:**',
      `[1] quip-source-v1:${encodedTitle} - https://trusted.example/article`,
    ].join('\n');
    const parsed = extractSources(footer);

    expect(parsed.sources).toEqual([
      expect.objectContaining({
        num: 1,
        title,
        url: 'https://trusted.example/article',
      }),
    ]);
    const body = document.createElement('div');
    body.innerHTML = renderMarkdown(parsed.cleanContent, parsed.sources);
    expect(body.querySelector('.source-badge')?.getAttribute('href')).toBe('https://trusted.example/article');

    const { container } = render(SourcesList, { props: { sources: parsed.sources } });
    const sourceCard = container.querySelector<HTMLAnchorElement>('.source-card');
    expect(sourceCard?.href).toBe('https://trusted.example/article');
    expect(sourceCard?.textContent).toContain(title);
    expect(container.querySelector('img[onerror]')).toBeNull();
    expect(container.querySelector('a[href="https://evil.example/"]')).toBeNull();
  });

  it('uses the trailing retrieved URL for legacy persisted footers with linked titles', () => {
    const legacyFooter = [
      'Answer [1].',
      '',
      '---',
      '**Sources:**',
      '[1] [click](https://evil.example) <img src=x onerror=alert(1)> - https://trusted.example/article',
    ].join('\n');
    const parsed = extractSources(legacyFooter);
    const { container } = render(SourcesList, { props: { sources: parsed.sources } });

    expect(container.querySelector<HTMLAnchorElement>('.source-card')?.href).toBe('https://trusted.example/article');
    expect(container.querySelector('img[onerror]')).toBeNull();
  });

  it('deduplicates repeated validated URLs and rejects unsafe URL syntax', () => {
    const footer = [
      '**Sources:**',
      `[1] quip-source-v1:${base64UrlUtf8('Trusted title')} - https://trusted.example/article`,
      `[2] quip-source-v1:${base64UrlUtf8('Duplicate title')} - https://trusted.example/article`,
      '[3] [malicious](javascript:alert(1))',
    ].join('\n');
    const parsed = extractSources(footer);
    const { container } = render(SourcesList, { props: { sources: parsed.sources } });

    expect(container.querySelectorAll('.source-card')).toHaveLength(1);
    expect(container.querySelector<HTMLAnchorElement>('.source-card')?.href).toBe('https://trusted.example/article');
  });
});
