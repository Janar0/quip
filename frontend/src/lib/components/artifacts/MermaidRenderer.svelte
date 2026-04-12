<script lang="ts">
  import { onMount } from 'svelte';

  let { content }: { content: string } = $props();
  let container = $state<HTMLDivElement | undefined>(undefined);
  let error = $state('');

  onMount(async () => {
    try {
      const mermaid = (await import('mermaid')).default;
      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        themeVariables: {
          darkMode: true,
          background: 'transparent',
          primaryColor: '#8b5cf6',
          primaryTextColor: '#e0e0e0',
          lineColor: '#555',
        },
      });
      const id = `mermaid-${Math.random().toString(36).slice(2, 8)}`;
      const { svg } = await mermaid.render(id, content);
      if (container) container.innerHTML = svg;
    } catch (e) {
      error = String(e);
    }
  });
</script>

{#if error}
  <div class="p-3">
    <p class="text-xs text-error-400 mb-2">Mermaid render error</p>
    <pre class="text-sm opacity-50 whitespace-pre-wrap">{content}</pre>
  </div>
{:else}
  <div bind:this={container} class="p-3 flex justify-center [&_svg]:max-w-full"></div>
{/if}
