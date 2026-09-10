import { expect, it } from 'vitest';
import { parseServerDate } from './time';

it('treats naive server timestamps as UTC', () => {
  expect(parseServerDate('2026-09-10T07:00:00').toISOString()).toBe('2026-09-10T07:00:00.000Z');
});
it('preserves explicit offsets', () => {
  expect(parseServerDate('2026-09-10T10:00:00+03:00').toISOString()).toBe('2026-09-10T07:00:00.000Z');
});
