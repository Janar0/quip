<script lang="ts">
  import type { Artifact } from '$lib/stores/chat';
  import PlotRenderer from './PlotRenderer.svelte';
  import ChartRenderer from './ChartRenderer.svelte';
  import TableRenderer from './TableRenderer.svelte';
  import CodeRenderer from './CodeRenderer.svelte';
  import MermaidRenderer from './MermaidRenderer.svelte';
  import HtmlRenderer from './HtmlRenderer.svelte';

  let { artifact }: { artifact: Artifact } = $props();

  let parsedData = $derived.by(() => {
    if (['plot', 'chart', 'table'].includes(artifact.type)) {
      try {
        return JSON.parse(artifact.content);
      } catch {
        return null;
      }
    }
    return null;
  });
</script>

{#if artifact.type === 'plot' && parsedData}
  <PlotRenderer data={parsedData} />
{:else if artifact.type === 'chart' && parsedData}
  <ChartRenderer data={parsedData} />
{:else if artifact.type === 'table' && parsedData}
  <TableRenderer data={parsedData} />
{:else if artifact.type === 'mermaid'}
  <MermaidRenderer content={artifact.content} />
{:else if artifact.type === 'svg'}
  <div class="p-3 flex justify-center [&_svg]:max-w-full">
    {@html artifact.content}
  </div>
{:else if artifact.type === 'html'}
  <HtmlRenderer content={artifact.content} title={artifact.title} />
{:else}
  <CodeRenderer content={artifact.content} language={artifact.language ?? ''} />
{/if}
