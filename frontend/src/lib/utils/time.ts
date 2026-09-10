/** SQLite timestamps are UTC even when serialized without a timezone suffix. */
export function parseServerDate(value: string): Date {
  const normalized = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(value)
    ? value.replace(' ', 'T') + 'Z'
    : value;
  return new Date(normalized);
}

export function getTimeGroup(dateStr: string): string {
  const date = parseServerDate(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  if (diffDays < 1 && date.getDate() === now.getDate()) return 'today';
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.getDate() === yesterday.getDate() && date.getMonth() === yesterday.getMonth() && date.getFullYear() === yesterday.getFullYear()) return 'yesterday';
  if (diffDays < 7) return 'week';
  if (diffDays < 30) return 'month';
  return 'older';
}

export function formatRelativeTime(dateStr: string): string {
  const diffMs = Date.now() - parseServerDate(dateStr).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return parseServerDate(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
