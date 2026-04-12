<script lang="ts">
  import { locale } from 'svelte-i18n';
  import { getRandomBackronym, getAppName } from '$lib/quip/backronyms';

  let appName = $derived(getAppName($locale ?? 'en'));
  let backronym = $state(getRandomBackronym($locale ?? 'en'));

  $effect(() => {
    if ($locale) backronym = getRandomBackronym($locale);
  });
</script>

<div class="text-center select-none">
  <span class="text-xl font-black tracking-widest">{appName}</span>
  <p class="text-xs opacity-40 italic truncate max-w-48">{backronym}</p>
</div>
