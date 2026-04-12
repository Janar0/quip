<script lang="ts">
  import { t } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { getBudgets, upsertBudget, deleteBudget, getUsers, type BudgetItem, type AdminUser } from '$lib/api/admin';
  import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

  let budgets = $state<BudgetItem[]>([]);
  let users = $state<AdminUser[]>([]);
  let loading = $state(true);
  let deletingId = $state<string | null>(null);

  // Form state
  let formUserId = $state<string>('');
  let formPeriod = $state<string>('monthly');
  let formLimit = $state<number>(10);
  let saving = $state(false);

  onMount(async () => {
    [budgets, users] = await Promise.all([getBudgets(), getUsers()]);
    loading = false;
  });

  async function handleSave() {
    saving = true;
    const ok = await upsertBudget({
      user_id: formUserId || null,
      period: formPeriod,
      limit_usd: formLimit,
    });
    if (ok) {
      toast.success($t('toast.budgetSaved'));
      budgets = await getBudgets();
      formUserId = '';
      formLimit = 10;
    } else {
      toast.error($t('toast.budgetFailed'));
    }
    saving = false;
  }

  async function confirmDelete() {
    if (!deletingId) return;
    const ok = await deleteBudget(deletingId);
    if (ok) {
      budgets = budgets.filter((b) => b.id !== deletingId);
      toast.success($t('toast.budgetDeleted'));
    } else {
      toast.error($t('toast.budgetDeleteFailed'));
    }
    deletingId = null;
  }
</script>

<ConfirmDialog
  open={!!deletingId}
  title={$t('admin.confirmDeleteBudget')}
  message={$t('admin.confirmDeleteBudgetMsg')}
  onConfirm={confirmDelete}
  onCancel={() => (deletingId = null)}
/>

<div class="p-8 max-w-3xl space-y-6">
  <h1 class="text-2xl font-bold">{$t('admin.budgets')}</h1>
  <p class="text-sm opacity-40">{$t('admin.budgetsDesc')}</p>

  <!-- Add/Edit form -->
  <section class="card p-6 space-y-4">
    <h2 class="text-lg font-semibold">{$t('admin.addBudget')}</h2>
    <div class="grid grid-cols-3 gap-4">
      <div>
        <label for="budget-user" class="text-xs opacity-50 mb-1 block">{$t('admin.budgetUser')}</label>
        <select id="budget-user" class="select text-sm w-full" bind:value={formUserId}>
          <option value="">{$t('admin.budgetGlobal')}</option>
          {#each users as u}
            <option value={u.id}>{u.name} ({u.email})</option>
          {/each}
        </select>
      </div>
      <div>
        <label for="budget-period" class="text-xs opacity-50 mb-1 block">{$t('admin.budgetPeriod')}</label>
        <select id="budget-period" class="select text-sm w-full" bind:value={formPeriod}>
          <option value="daily">{$t('admin.budgetDaily')}</option>
          <option value="monthly">{$t('admin.budgetMonthly')}</option>
        </select>
      </div>
      <div>
        <label for="budget-limit" class="text-xs opacity-50 mb-1 block">{$t('admin.budgetLimit')}</label>
        <input id="budget-limit" type="number" class="input text-sm w-full" bind:value={formLimit} min="0" step="0.5" />
      </div>
    </div>
    <button class="btn preset-filled-slate-600" onclick={handleSave} disabled={saving || formLimit <= 0}>
      {saving ? '...' : $t('common.save')}
    </button>
  </section>

  <!-- Budget list -->
  {#if loading}
    <div class="space-y-2">
      {#each [1,2] as _}
        <div class="h-14 bg-slate-800/30 rounded-lg animate-pulse"></div>
      {/each}
    </div>
  {:else if budgets.length === 0}
    <p class="text-center opacity-40 py-8">{$t('admin.noBudgets')}</p>
  {:else}
    <div class="space-y-2">
      {#each budgets as budget (budget.id)}
        <div class="card p-4 flex items-center justify-between">
          <div>
            <span class="font-medium">{budget.user_name ?? $t('admin.budgetGlobal')}</span>
            <span class="text-xs opacity-40 ml-2">{$t(budget.period === 'daily' ? 'admin.budgetDaily' : 'admin.budgetMonthly')}</span>
          </div>
          <div class="flex items-center gap-3">
            <span class="font-mono text-sm">${budget.limit_usd.toFixed(2)}</span>
            <button
              class="p-1 rounded opacity-40 hover:opacity-100 hover:text-error-400 transition-colors"
              onclick={() => (deletingId = budget.id)}
              aria-label={$t('confirm.delete')}
            >
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
