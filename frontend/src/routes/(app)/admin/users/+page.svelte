<script lang="ts">
  import { t } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { currentUser } from '$lib/stores/auth';
  import { getUsers, updateUserRole, updateUserStatus, deleteUser, changeUserPassword, type AdminUser } from '$lib/api/admin';
  import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

  let users = $state<AdminUser[]>([]);
  let loading = $state(true);
  let search = $state('');
  let sortBy = $state<'name' | 'email' | 'role'>('name');
  let sortAsc = $state(true);
  let deletingUser = $state<AdminUser | null>(null);
  let passwordUser = $state<AdminUser | null>(null);
  let newPassword = $state('');
  let savingPassword = $state(false);

  function formatLastActive(ts: string | null): string {
    if (!ts) return '—';
    const d = new Date(ts);
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString();
  }

  async function submitPasswordChange() {
    if (!passwordUser || newPassword.length < 8) return;
    savingPassword = true;
    const ok = await changeUserPassword(passwordUser.id, newPassword);
    if (ok) {
      toast.success($t('admin.users.passwordChanged'));
      passwordUser = null;
      newPassword = '';
    } else {
      toast.error($t('common.error'));
    }
    savingPassword = false;
  }

  let filtered = $derived.by(() => {
    let list = users;
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (u) => u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q) || u.username.toLowerCase().includes(q),
      );
    }
    list = [...list].sort((a, b) => {
      const va = a[sortBy];
      const vb = b[sortBy];
      return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    });
    return list;
  });

  onMount(async () => {
    users = await getUsers();
    loading = false;
  });

  function toggleSort(col: 'name' | 'email' | 'role') {
    if (sortBy === col) sortAsc = !sortAsc;
    else { sortBy = col; sortAsc = true; }
  }

  async function changeRole(user: AdminUser, newRole: string) {
    const ok = await updateUserRole(user.id, newRole);
    if (ok) {
      users = users.map((u) => (u.id === user.id ? { ...u, role: newRole } : u));
      toast.success($t('toast.roleChanged'));
    } else {
      toast.error($t('toast.roleChangeFailed'));
    }
  }

  async function toggleStatus(user: AdminUser) {
    const ok = await updateUserStatus(user.id, !user.is_active);
    if (ok) {
      users = users.map((u) => (u.id === user.id ? { ...u, is_active: !user.is_active } : u));
      toast.success($t(user.is_active ? 'toast.userDisabled' : 'toast.userEnabled'));
    } else {
      toast.error($t('common.error'));
    }
  }

  async function confirmDeleteUser() {
    if (!deletingUser) return;
    const ok = await deleteUser(deletingUser.id);
    if (ok) {
      users = users.filter((u) => u.id !== deletingUser!.id);
      toast.success($t('toast.userDeleted'));
    } else {
      toast.error($t('common.error'));
    }
    deletingUser = null;
  }

  const roleBadge: Record<string, string> = {
    admin: 'bg-slate-800 text-slate-200',
    user: 'bg-success-500/15 text-success-400',
    pending: 'bg-warning-500/15 text-warning-400',
  };
</script>

<ConfirmDialog
  open={!!deletingUser}
  title={$t('admin.confirmDeleteUser')}
  message={$t('admin.confirmDeleteUserMsg')}
  onConfirm={confirmDeleteUser}
  onCancel={() => (deletingUser = null)}
/>

{#if passwordUser}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div class="card p-6 w-full max-w-sm space-y-4 mx-4">
      <h2 class="font-semibold">{$t('admin.users.changePassword')}</h2>
      <p class="text-sm opacity-50">{passwordUser.name} · {passwordUser.email}</p>
      <input
        type="password"
        class="input w-full"
        placeholder={$t('admin.users.newPassword')}
        bind:value={newPassword}
        onkeydown={(e) => e.key === 'Enter' && submitPasswordChange()}
        autofocus
      />
      {#if newPassword.length > 0 && newPassword.length < 8}
        <p class="text-xs text-error-400">Min 8 characters</p>
      {/if}
      <div class="flex gap-2 justify-end">
        <button class="btn" onclick={() => { passwordUser = null; newPassword = ''; }}>{$t('common.cancel')}</button>
        <button
          class="btn preset-filled-primary-500"
          onclick={submitPasswordChange}
          disabled={newPassword.length < 8 || savingPassword}
        >
          {savingPassword ? '...' : $t('common.save')}
        </button>
      </div>
    </div>
  </div>
{/if}

<div class="p-8 max-w-4xl space-y-5">
  <!-- Header -->
  <div class="flex items-center justify-between gap-4">
    <h1 class="text-2xl font-bold">{$t('admin.tabs.users')}</h1>
    <span class="text-sm opacity-40">{users.length} total</span>
  </div>

  <!-- Search -->
  <div class="relative">
    <svg class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 opacity-30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
    <input
      type="text"
      class="input pl-10 w-full"
      placeholder={$t('admin.usersSearch')}
      bind:value={search}
    />
  </div>

  {#if loading}
    <div class="space-y-2">
      {#each [1,2,3,4] as _}
        <div class="h-14 bg-slate-800/30 rounded-lg animate-pulse"></div>
      {/each}
    </div>
  {:else if filtered.length === 0}
    <p class="text-center opacity-40 py-8">{$t('admin.noUsersFound')}</p>
  {:else}
    <div class="table-container rounded-lg overflow-hidden">
      <table class="table text-sm">
        <thead>
          <tr class="border-b border-slate-800">
            {#each [['name', 'Name'], ['email', 'Email'], ['role', 'Role']] as [col, label]}
              <th
                class="px-4 py-3 cursor-pointer select-none hover:bg-slate-800/30 transition-colors"
                onclick={() => toggleSort(col as 'name' | 'email' | 'role')}
              >
                <div class="flex items-center gap-1.5">
                  {label}
                  {#if sortBy === col}
                    <svg class="w-3 h-3 opacity-60" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                      {#if sortAsc}<path d="M18 15l-6-6-6 6"/>{:else}<path d="M6 9l6 6 6-6"/>{/if}
                    </svg>
                  {/if}
                </div>
              </th>
            {/each}
            <th class="px-4 py-3">Status</th>
            <th class="px-4 py-3">{$t('admin.users.lastActive')}</th>
            <th class="px-4 py-3 w-40">Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each filtered as user (user.id)}
            {@const isSelf = user.id === $currentUser?.id}
            <tr class="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
              <td class="px-4 py-3">
                <div class="flex items-center gap-2.5">
                  <div class="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-xs font-bold text-slate-300 shrink-0">
                    {user.name.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <div class="font-medium">{user.name}</div>
                    <div class="text-xs opacity-40">@{user.username}</div>
                  </div>
                </div>
              </td>
              <td class="px-4 py-3 opacity-60">{user.email}</td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center text-xs font-medium px-2.5 py-1 rounded-full uppercase tracking-wide {roleBadge[user.role] ?? 'bg-slate-800/40 text-slate-400'}">
                  {user.role}
                </span>
              </td>
              <td class="px-4 py-3">
                <button
                  class="inline-flex items-center gap-1.5 text-xs disabled:opacity-30"
                  onclick={() => toggleStatus(user)}
                  disabled={isSelf}
                  title={$t(user.is_active ? 'admin.disableUser' : 'admin.enableUser')}
                >
                  {#if user.is_active}
                    <span class="relative flex size-1.5">
                      <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-success-400 opacity-75"></span>
                      <span class="relative inline-flex size-1.5 rounded-full bg-success-500"></span>
                    </span>
                    {$t('common.enabled')}
                  {:else}
                    <span class="size-1.5 rounded-full bg-slate-600"></span>
                    {$t('common.disabled')}
                  {/if}
                </button>
              </td>
              <td class="px-4 py-3 text-xs opacity-50 whitespace-nowrap">
                {formatLastActive(user.last_active_at)}
              </td>
              <td class="px-4 py-3">
                <div class="flex items-center gap-2">
                  <select
                    class="select text-xs w-24 py-1"
                    value={user.role}
                    onchange={(e) => changeRole(user, e.currentTarget.value)}
                  >
                    <option value="admin">admin</option>
                    <option value="user">user</option>
                    <option value="pending">pending</option>
                  </select>
                  <button
                    class="p-1 rounded opacity-40 hover:opacity-100 hover:text-primary-400 transition-colors"
                    onclick={() => { passwordUser = user; newPassword = ''; }}
                    title={$t('admin.users.changePassword')}
                  >
                    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="8" cy="15" r="4"/><path d="M10.85 12.15L19 4M18 5l2 2M15 8l2 2"/></svg>
                  </button>
                  <button
                    class="p-1 rounded opacity-40 hover:opacity-100 hover:text-error-400 transition-colors disabled:opacity-10 disabled:hover:text-current"
                    onclick={() => (deletingUser = user)}
                    disabled={isSelf}
                    title={$t('admin.deleteUser')}
                  >
                    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                  </button>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
