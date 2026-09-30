import english from './locales/en.json';
import russian from './locales/ru.json';
import { describe, expect, it } from 'vitest';

describe('chat UI translations', () => {
  it.each([
    ['English', english],
    ['Russian', russian],
  ])('provides visible model and drawer labels in %s', (_language, messages) => {
    expect(messages['common.close']).toBeTruthy();
    expect(messages['models.search']).toBeTruthy();
    expect(messages['models.noSearchResults']).toBeTruthy();
    expect(messages['models.nextResponse']).toBeTruthy();
    expect(messages['artifacts.panelLabel']).toBeTruthy();
  });
});
