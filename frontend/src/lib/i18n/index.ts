import { register, init, getLocaleFromNavigator } from 'svelte-i18n';

register('en', () => import('./locales/en.json'));
register('ru', () => import('./locales/ru.json'));

const storedLocale = typeof localStorage !== 'undefined' ? localStorage.getItem('locale') : null;

init({
  fallbackLocale: 'en',
  initialLocale: storedLocale || getLocaleFromNavigator() || 'en',
});
