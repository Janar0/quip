<script lang="ts">
  import { t } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { getUsage, type UsageData } from '$lib/api/admin';

  let data = $state<UsageData | null>(null);
  let loading = $state(true);
  let days = $state(30);

  async function load() {
    loading = true;
    data = await getUsage(days);
    loading = false;
  }

  onMount(load);

  function fmt(n: number): string {
    return n < 0.01 ? n.toFixed(6) : n.toFixed(4);
  }

  function fmtTokens(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
  }

  // Simple bar width for cost visualization
  function barWidth(value: number, max: number): string {
    if (!max) return '0%';
    return Math.max(2, (value / max) * 100) + '%';
  }

  function fmtDay(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
</script>

<div class="p-8 max-w-4xl mx-auto space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-bold">{$t('admin.usage')}</h1>
    <div class="flex gap-2">
      {#each [7, 30, 90] as d}
        <button
          class="btn btn-sm {days === d ? 'preset-filled' : 'preset-outlined'}"
          onclick={() => { days = d; load(); }}
        >{d}d</button>
      {/each}
    </div>
  </div>

  {#if loading}
    <div class="space-y-6">
      <!-- Summary cards skeleton -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        {#each [1,2,3,4] as _}
          <div class="card p-4 text-center animate-pulse">
            <div class="h-8 w-20 mx-auto bg-slate-800/50 rounded mb-2"></div>
            <div class="h-3 w-16 mx-auto bg-slate-800/30 rounded"></div>
          </div>
        {/each}
      </div>
      <!-- By Model skeleton -->
      <div class="card p-6 space-y-3 animate-pulse">
        <div class="h-5 w-24 bg-slate-800/50 rounded"></div>
        {#each [1,2,3] as _}
          <div class="space-y-1">
            <div class="flex justify-between">
              <div class="h-4 w-48 bg-slate-800/30 rounded"></div>
              <div class="h-4 w-16 bg-slate-800/30 rounded"></div>
            </div>
            <div class="h-1.5 bg-slate-800/30 rounded-full"></div>
          </div>
        {/each}
      </div>
      <!-- By User skeleton -->
      <div class="card p-6 space-y-3 animate-pulse">
        <div class="h-5 w-20 bg-slate-800/50 rounded"></div>
        {#each [1,2,3] as _}
          <div class="h-10 bg-slate-800/30 rounded"></div>
        {/each}
      </div>
    </div>
  {:else if !data}
    <p class="opacity-50">{$t('admin.usageFailedToLoad')}</p>
  {:else}
    <!-- Summary Cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="card p-4 text-center">
        <div class="text-2xl font-bold">${fmt(data.totals.cost)}</div>
        <div class="text-xs opacity-50">{$t('admin.usageTotalCost')}</div>
      </div>
      <div class="card p-4 text-center">
        <div class="text-2xl font-bold">{data.totals.requests}</div>
        <div class="text-xs opacity-50">{$t('admin.usageRequests')}</div>
      </div>
      <div class="card p-4 text-center">
        <div class="text-2xl font-bold">{fmtTokens(data.totals.prompt_tokens + data.totals.completion_tokens)}</div>
        <div class="text-xs opacity-50">{$t('admin.usageTotalTokens')}</div>
      </div>
      <div class="card p-4 text-center">
        <div class="text-2xl font-bold">{fmtTokens(data.totals.cached_tokens)}</div>
        <div class="text-xs opacity-50">{$t('admin.usageCachedTokens')}</div>
      </div>
    </div>

    <!-- By Model -->
    {#if data.by_model.length > 0}
      {@const maxCost = Math.max(...data.by_model.map((m) => m.cost))}
      {@const maxReq = Math.max(...data.by_model.map((m) => m.requests))}
      <section class="card p-6 space-y-3">
        <h2 class="text-lg font-semibold">{$t('admin.usageByModel')}</h2>
        {#each data.by_model as row}
          <div class="space-y-1">
            <div class="flex justify-between text-sm">
              <span class="truncate flex-1">{row.display_name}</span>
              <span class="opacity-40 ml-2 text-xs">{fmtTokens(row.tokens)} tok</span>
              <span class="opacity-70 ml-2">{row.requests} {$t('admin.usageReq')}</span>
              <span class="ml-3 font-mono">${fmt(row.cost)}</span>
            </div>
            <div class="h-1.5 bg-slate-800/50 rounded-full overflow-hidden">
              <div class="h-full bg-primary-500/60 rounded-full"
                style="width: {maxCost > 0 ? barWidth(row.cost, maxCost) : barWidth(row.requests, maxReq)}">
              </div>
            </div>
          </div>
        {/each}
      </section>
    {/if}

    <!-- By User -->
    {#if data.by_user.length > 0}
      <section class="card p-6 space-y-3">
        <h2 class="text-lg font-semibold">{$t('admin.usageByUser')}</h2>
        <div class="table-container">
          <table class="table text-sm">
            <thead>
              <tr>
                <th>{$t('admin.usageUser')}</th>
                <th class="text-right">{$t('admin.usageRequests')}</th>
                <th class="text-right">{$t('admin.usageCost')}</th>
              </tr>
            </thead>
            <tbody>
              {#each data.by_user as row}
                <tr>
                  <td>
                    <div>{row.name}</div>
                    <div class="text-xs opacity-50">{row.email}</div>
                  </td>
                  <td class="text-right">{row.requests}</td>
                  <td class="text-right font-mono">${fmt(row.cost)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>
    {/if}

    <!-- By Day -->
    {#if data.by_day.length > 0}
      {@const maxDayCost = Math.max(...data.by_day.map((d) => d.cost))}
      {@const maxDayReq = Math.max(...data.by_day.map((d) => d.requests))}
      <section class="card p-6 space-y-3">
        <h2 class="text-lg font-semibold">{$t('admin.usageDaily')}</h2>
        <div class="space-y-1">
          {#each data.by_day as row}
            <div class="flex items-center gap-2 text-sm">
              <span class="w-16 opacity-60 text-xs font-mono shrink-0">{fmtDay(row.day)}</span>
              <div class="flex-1 h-3 bg-slate-800/50 rounded overflow-hidden">
                <div class="h-full bg-primary-500/50 rounded"
                  style="width: {maxDayCost > 0 ? barWidth(row.cost, maxDayCost) : barWidth(row.requests, maxDayReq)}">
                </div>
              </div>
              <span class="w-8 text-right opacity-50 text-xs shrink-0">{row.requests}</span>
              <span class="w-20 text-right font-mono text-xs shrink-0">${fmt(row.cost)}</span>
            </div>
          {/each}
        </div>
      </section>
    {/if}
  {/if}
</div>
