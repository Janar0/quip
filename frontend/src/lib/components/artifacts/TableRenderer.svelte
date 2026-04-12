<script lang="ts">
  interface TableColumn {
    key: string;
    label: string;
    sortable?: boolean;
    align?: 'left' | 'right' | 'center';
  }

  interface TableData {
    columns: TableColumn[];
    rows: Record<string, unknown>[];
  }

  let { data }: { data: TableData } = $props();
  let sortKey = $state('');
  let sortAsc = $state(true);

  let sortedRows = $derived.by(() => {
    if (!sortKey) return data.rows;
    return [...data.rows].sort((a, b) => {
      const va = a[sortKey];
      const vb = b[sortKey];
      const cmp =
        typeof va === 'number' && typeof vb === 'number'
          ? va - vb
          : String(va ?? '').localeCompare(String(vb ?? ''));
      return sortAsc ? cmp : -cmp;
    });
  });

  function toggleSort(key: string) {
    if (sortKey === key) sortAsc = !sortAsc;
    else {
      sortKey = key;
      sortAsc = true;
    }
  }
</script>

<div class="overflow-x-auto">
  <table class="w-full text-sm">
    <thead>
      <tr class="border-b" style="border-color: var(--quip-border-strong)">
        {#each data.columns as col}
          <th
            class="px-3 py-2 text-left text-xs opacity-50 font-medium {col.sortable !== false ? 'cursor-pointer hover:opacity-100' : ''}"
            class:text-right={col.align === 'right'}
            class:text-center={col.align === 'center'}
            onclick={() => col.sortable !== false && toggleSort(col.key)}
          >
            {col.label}
            {#if sortKey === col.key}
              <span class="ml-0.5">{sortAsc ? '\u2191' : '\u2193'}</span>
            {/if}
          </th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each sortedRows as row, i}
        <tr class="border-b border-slate-800/50 {i % 2 ? 'bg-slate-900/20' : ''}">
          {#each data.columns as col}
            <td
              class="px-3 py-2"
              class:text-right={col.align === 'right'}
              class:text-center={col.align === 'center'}
            >
              {row[col.key] ?? ''}
            </td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>
