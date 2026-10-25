<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from 'svelte-i18n';
  import { getUsers } from '$lib/api/admin';
  import { mountRoki } from '$lib/api/roki';
  import AdminPageHeader from '$lib/components/admin/AdminPageHeader.svelte';

  let host: HTMLDivElement;
  let failed = $state(false);

  onMount(() => {
    let admin: HTMLElement | null = null;
    // Roki knows people by Quip id; show their Quip names instead.
    getUsers()
      .then((users) => Object.fromEntries(users.map((u) => [u.id, u.name || u.username])))
      .catch(() => ({}))
      .then((names) => mountRoki(host, 'roki-admin', { names }))
      .then((element) => (admin = element))
      .catch(() => (failed = true));
    return () => admin?.remove();
  });
</script>

<div class="admin-page">
 <div class="max-w-5xl mx-auto">
  <AdminPageHeader
    icon="M12 2a10 10 0 100 20 10 10 0 000-20zM8 10h.01M16 10h.01M8 15c2 2 6 2 8 0"
    title={$t('admin.roki.title')}
    description={$t('admin.roki.description')}
  />
  {#if failed}
    <p class="text-sm text-muted">{$t('roki.loadFailed')}</p>
  {/if}
  <div bind:this={host} hidden={failed}></div>
 </div>
</div>
