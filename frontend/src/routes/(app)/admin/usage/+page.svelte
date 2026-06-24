<script lang="ts">
  import { t } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { D2 } from '$lib/motion';
  import { getUsage, type UsageData } from '$lib/api/admin';
  import AdminPageHeader from '$lib/components/admin/AdminPageHeader.svelte';
  import AdminCard from '$lib/components/admin/AdminCard.svelte';

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

<div class="admin-page" in:fly={{ y: 8, duration: D2 }}>
 <div class="max-w-4xl mx-auto">
  <AdminPageHeader icon="M18 20V10M12 20V4M6 20v-6" title={$t('admin.usage')}>
    {#snippet actions()}
      <div class="flex gap-1.5">
        {#each [7, 30, 90] as d}
          <button
            class="btn btn-sm {days === d ? 'preset-filled' : 'preset-outlined'}"
            onclick={() => { days = d; load(); }}
          >{d}d</button>
        {/each}
      </div>
    {/snippet}
  </AdminPageHeader>

  {#if loading}
    <div class="space-y-4">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        {#each [1,2,3,4] as _}
          <div class="admin-stat animate-pulse">
            <div class="h-3 w-16 bg-slate-800/30 rounded mb-2"></div>
            <div class="h-6 w-20 bg-slate-800/50 rounded"></div>
          </div>
        {/each}
      </div>
      <div class="admin-card animate-pulse space-y-3">
        <div class="h-5 w-24 bg-slate-800/50 rounded"></div>
        {#each [1,2,3] as _}
          <div class="h-8 bg-slate-800/30 rounded"></div>
        {/each}
      </div>
    </div>
  {:else if !data}
    <p class="opacity-50">{$t('admin.usageFailedToLoad')}</p>
  {:else}
    <!-- Summary Cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <div class="admin-stat">
        <div class="admin-stat-label">{$t('admin.usageTotalCost')}</div>
        <div class="admin-stat-value">${fmt(data.totals.cost)}</div>
      </div>
      <div class="admin-stat">
        <div class="admin-stat-label">{$t('admin.usageRequests')}</div>
        <div class="admin-stat-value">{data.totals.requests}</div>
      </div>
      <div class="admin-stat">
        <div class="admin-stat-label">{$t('admin.usageTotalTokens')}</div>
        <div class="admin-stat-value">{fmtTokens(data.totals.prompt_tokens + data.totals.completion_tokens)}</div>
      </div>
      <div class="admin-stat">
        <div class="admin-stat-label">{$t('admin.usageCachedTokens')}</div>
        <div class="admin-stat-value">{fmtTokens(data.totals.cached_tokens)}</div>
      </div>
    </div>

    <!-- By Model -->
    {#if data.by_model.length > 0}
      {@const maxCost = Math.max(...data.by_model.map((m) => m.cost))}
      {@const maxReq = Math.max(...data.by_model.map((m) => m.requests))}
      <AdminCard title={$t('admin.usageByModel')}>
        <div class="space-y-2.5">
          {#each data.by_model as row}
            <div class="space-y-1">
              <div class="flex items-baseline gap-2 text-sm">
                <span class="truncate flex-1 min-w-0">{row.display_name}</span>
                <span class="font-mono shrink-0">${fmt(row.cost)}</span>
              </div>
              <div class="flex items-center gap-2">
                <div class="flex-1 h-1.5 bg-slate-800/50 rounded-full overflow-hidden">
                  <div class="h-full bg-primary-500/60 rounded-full"
                    style="width: {maxCost > 0 ? barWidth(row.cost, maxCost) : barWidth(row.requests, maxReq)}">
                  </div>
                </div>
                <span class="text-[11px] opacity-40 shrink-0 whitespace-nowrap">{fmtTokens(row.tokens)} tok · {row.requests} {$t('admin.usageReq')}</span>
              </div>
            </div>
          {/each}
        </div>
      </AdminCard>
    {/if}

    <!-- By User -->
    {#if data.by_user.length > 0}
      <AdminCard title={$t('admin.usageByUser')}>
        <div class="admin-table-scroll">
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
      </AdminCard>
    {/if}

    <!-- By Day -->
    {#if data.by_day.length > 0}
      {@const maxDayCost = Math.max(...data.by_day.map((d) => d.cost))}
      {@const maxDayReq = Math.max(...data.by_day.map((d) => d.requests))}
      <AdminCard title={$t('admin.usageDaily')}>
        <div class="space-y-1">
          {#each data.by_day as row}
            <div class="flex items-center gap-2 text-sm">
              <span class="w-12 sm:w-16 opacity-60 text-xs font-mono shrink-0">{fmtDay(row.day)}</span>
              <div class="flex-1 h-3 bg-slate-800/50 rounded overflow-hidden">
                <div class="h-full bg-primary-500/50 rounded"
                  style="width: {maxDayCost > 0 ? barWidth(row.cost, maxDayCost) : barWidth(row.requests, maxDayReq)}">
                </div>
              </div>
              <span class="w-8 text-right opacity-50 text-xs shrink-0">{row.requests}</span>
              <span class="w-16 sm:w-20 text-right font-mono text-xs shrink-0">${fmt(row.cost)}</span>
            </div>
          {/each}
        </div>
      </AdminCard>
    {/if}
  {/if}
 </div>
</div>
