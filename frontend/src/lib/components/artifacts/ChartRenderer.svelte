<script lang="ts">
  import { onMount } from 'svelte';

  interface ChartDataset {
    label: string;
    data: number[];
    color?: string;
  }

  interface ChartData {
    chartType: string;
    labels: string[];
    datasets: ChartDataset[];
    options?: { stacked?: boolean; showLegend?: boolean };
  }

  let { data }: { data: ChartData } = $props();
  let canvas: HTMLCanvasElement;

  onMount(async () => {
    const { Chart, registerables } = await import('chart.js');
    Chart.register(...registerables);

    const isPie = data.chartType === 'pie' || data.chartType === 'doughnut';

    new Chart(canvas, {
      type: data.chartType as 'bar',
      data: {
        labels: data.labels,
        datasets: data.datasets.map((d) => ({
          label: d.label,
          data: d.data,
          backgroundColor: isPie
            ? d.data.map((_, i) => `hsl(${(i * 360) / d.data.length}, 70%, 55%)`)
            : (d.color ?? '#8b5cf6') + '80',
          borderColor: d.color ?? '#8b5cf6',
          borderWidth: isPie ? 0 : 2,
          tension: 0.3,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: {
            display: data.options?.showLegend ?? true,
            labels: { color: '#aaa', font: { size: 11 } },
          },
        },
        scales: isPie
          ? {}
          : {
              x: {
                ticks: { color: '#666' },
                grid: { color: '#222' },
                stacked: data.options?.stacked ?? false,
              },
              y: {
                ticks: { color: '#666' },
                grid: { color: '#222' },
                stacked: data.options?.stacked ?? false,
              },
            },
      },
    });
  });
</script>

<div class="p-3">
  <canvas bind:this={canvas}></canvas>
</div>
