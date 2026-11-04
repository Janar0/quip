import { describe, expect, it, vi } from 'vitest';
import { endRakazoSession, rakazoEntry, safeNext } from './rakazo';

const ORIGIN = 'https://quip.example.test';

describe('safeNext', () => {
  it('keeps a path on this site with its query', () => {
    expect(safeNext('/api/oidc/authorize?state=a%20b&x=1', ORIGIN)).toBe('/api/oidc/authorize?state=a%20b&x=1');
    expect(safeNext('/rakazo', ORIGIN)).toBe('/rakazo');
  });

  it.each([
    'https://evil.example.test/',
    '//evil.example.test/',
    '/\\evil.example.test/',
    '\\\\evil.example.test/',
    '/\t/evil.example.test/',
    'javascript:alert(1)',
    'data:text/html,x',
  ])('rejects %s', (next) => {
    expect(safeNext(next, ORIGIN)).toBeNull();
  });

  it('treats a missing or broken value as no destination', () => {
    expect(safeNext(null, ORIGIN)).toBeNull();
    expect(safeNext('', ORIGIN)).toBeNull();
    expect(safeNext('http://[broken', ORIGIN)).toBeNull();
  });
});

describe('rakazoEntry', () => {
  it('carries the email in the fragment, which never reaches a server', () => {
    const url = new URL(rakazoEntry('https://rakazo.example.test', 'a+b@quip.dev', 'light'));
    expect(url.origin).toBe('https://rakazo.example.test');
    expect(url.pathname).toBe('/quip/entry');
    expect(url.search).toBe('');
    expect(new URLSearchParams(url.hash.slice(1)).get('email')).toBe('a+b@quip.dev');
    expect(new URLSearchParams(url.hash.slice(1)).get('theme')).toBe('light');
  });
});

describe('endRakazoSession', () => {
  const RAKAZO = 'https://rakazo.example.test';

  it('finishes when the Rakazo sign-out page reports back, and removes its frame', async () => {
    const done = endRakazoSession(RAKAZO);
    const frame = document.querySelector('iframe');
    expect(frame?.getAttribute('src')).toBe(`${RAKAZO}/quip/signout`);
    window.dispatchEvent(new MessageEvent('message', { origin: RAKAZO, data: 'rakazo-signed-out' }));
    await done;
    expect(document.querySelector('iframe')).toBeNull();
  });

  it('ignores the same message from another site', async () => {
    vi.useFakeTimers();
    let finished = false;
    const done = endRakazoSession(RAKAZO).then(() => (finished = true));
    window.dispatchEvent(new MessageEvent('message', { origin: 'https://evil.example.test', data: 'rakazo-signed-out' }));
    await vi.advanceTimersByTimeAsync(1);
    expect(finished).toBe(false);
    await vi.advanceTimersByTimeAsync(5000);
    await done;
    vi.useRealTimers();
  });

  it('does not hold up Quip logout when Rakazo never answers', async () => {
    vi.useFakeTimers();
    const done = endRakazoSession(RAKAZO);
    await vi.advanceTimersByTimeAsync(5000);
    await done;
    expect(document.querySelector('iframe')).toBeNull();
    vi.useRealTimers();
  });
});
