<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from 'svelte-i18n';
  import { showSidebar } from '$lib/stores/ui';
  import { mountRoki, rokiPresence, type RokiState } from '$lib/api/roki';

  let host: HTMLDivElement;
  let failed = $state(false);

  onMount(() => {
    let room: HTMLElement | null = null;
    const onPresence = (event: Event) =>
      rokiPresence.set(((event as CustomEvent).detail?.state ?? '') as RokiState);
    mountRoki(host, 'roki-room')
      .then((element) => {
        room = element;
        room.addEventListener('roki-presence', onPresence);
      })
      .catch(() => (failed = true));
    return () => {
      room?.removeEventListener('roki-presence', onPresence);
      room?.remove();
    };
  });
</script>

<svelte:head><title>Roki · QUIP</title></svelte:head>

<!-- Leave room for the floating sidebar button when the sidebar is hidden. -->
<div class="flex-1 min-h-0 flex flex-col" style="--roki-head-inset: {$showSidebar ? '16px' : '60px'}">
  {#if failed}
    <p class="m-auto text-sm text-muted">{$t('roki.loadFailed')}</p>
  {/if}
  <div bind:this={host} class="flex-1 min-h-0" hidden={failed}></div>
</div>
