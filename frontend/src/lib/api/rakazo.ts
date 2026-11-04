import { writable } from 'svelte/store';

/**
 * Rakazo is an unmodified upstream install on its own origin, embedded in Quip and
 * signed in through Quip's OpenID Connect provider. An empty address keeps it hidden.
 */
export const rakazoUrl = writable('');

/** The embedded page signs in and then opens Rakazo. A fragment never reaches a server. */
export function rakazoEntry(url: string, email: string, theme: string): string {
  return `${url}/quip/entry#${new URLSearchParams({ email, theme })}`;
}

/** Only an address on this site may follow a login; browsers normalize the rest. */
export function safeNext(next: string | null | undefined, origin: string): string | null {
  if (!next) return null;
  try {
    const url = new URL(next, origin);
    return url.origin === origin ? `${url.pathname}${url.search}${url.hash}` : null;
  } catch {
    return null;
  }
}

/** Signing out of Quip must not leave the Rakazo session behind on a shared device. */
export function endRakazoSession(url: string, timeoutMs = 3000): Promise<void> {
  return new Promise((resolve) => {
    const frame = document.createElement('iframe');
    frame.hidden = true;
    frame.src = `${url}/quip/signout`;
    const finish = () => {
      clearTimeout(timer);
      window.removeEventListener('message', onMessage);
      frame.remove();
      resolve();
    };
    const onMessage = (event: MessageEvent) => {
      if (event.origin === url && event.data === 'rakazo-signed-out') finish();
    };
    const timer = setTimeout(finish, timeoutMs);
    window.addEventListener('message', onMessage);
    document.body.append(frame);
  });
}
