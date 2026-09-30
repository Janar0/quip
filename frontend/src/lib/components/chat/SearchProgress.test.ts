import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import SearchProgress from './SearchProgress.svelte';
import type { ToolExecution } from '$lib/stores/sandbox';

const executions: ToolExecution[] = [
  {
    id: 'search-1',
    name: 'web_search',
    arguments: JSON.stringify({ query: 'current source' }),
    status: 'completed',
    result: {
      status: 'partial',
      warning: 'Image search was unavailable.',
      results: [
        { title: 'Retrieved source', url: 'https://example.test/source', snippet: 'Evidence' },
        { title: 'Unsafe source', url: 'javascript:alert(1)', snippet: 'Not a source' },
      ],
    },
  },
];

afterEach(cleanup);

describe('SearchProgress source links', () => {
  it('hides result cards when the final answer already has its source footer', () => {
    render(SearchProgress, { props: { executions, showSourceLinks: false } });

    expect(screen.queryByRole('link', { name: /Retrieved source/ })).toBeNull();
    expect(screen.getByText(/Image search was unavailable/)).toBeTruthy();
  });

  it('counts and links only validated HTTP search results', () => {
    render(SearchProgress, { props: { executions } });

    expect(screen.getByRole('link', { name: /Retrieved source/ })).toBeTruthy();
    expect(screen.queryByRole('link', { name: /Unsafe source/ })).toBeNull();
    expect(screen.getByText('search.searched — 1 search.results')).toBeTruthy();
  });
});
