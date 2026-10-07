import { cleanup, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { addMessages, init, locale } from 'svelte-i18n';
import english from '$lib/i18n/locales/en.json';
import russian from '$lib/i18n/locales/ru.json';
import RegisterPage from './+page.svelte';

vi.unmock('svelte-i18n');
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/api/auth', () => ({
  getSetupStatus: vi.fn().mockResolvedValue({ required: true, admin_email_configured: true }),
  register: vi.fn(),
}));

beforeEach(() => {
  if (!Element.prototype.animate) {
    Object.defineProperty(Element.prototype, 'animate', {
      configurable: true,
      value: () => ({ cancel() {}, finish() {}, finished: Promise.resolve() }),
    });
  }
});
afterEach(cleanup);

describe('administrator registration', () => {
  it.each([
    ['en', english],
    ['ru', russian],
  ] as const)('requires the first-install token even with ADMIN_EMAIL configured in %s', async (language, messages) => {
    addMessages('en', english);
    addMessages('ru', russian);
    await init({ fallbackLocale: 'en', initialLocale: language });
    locale.set(language);
    render(RegisterPage);

    await waitFor(() => {
      const token = screen.getByLabelText(new RegExp(messages['auth.bootstrapToken'])) as HTMLInputElement;
      expect(token.required).toBe(true);
      expect(screen.getByText(messages['auth.bootstrapTokenHint'])).toBeTruthy();
    });
  });
});
