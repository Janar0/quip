<script lang="ts">
  import { evaluate } from '$lib/utils/matheval';

  interface PlotParam {
    name: string;
    label?: string;
    min: number;
    max: number;
    default: number;
    step: number;
  }

  interface PlotData {
    expression: string;
    xRange: [number, number];
    yRange?: [number, number] | null;
    params?: PlotParam[];
    showGrid?: boolean;
  }

  let { data }: { data: PlotData } = $props();

  let canvas: HTMLCanvasElement;
  let paramValues = $state<Record<string, number>>({});

  // Initialize param defaults
  $effect(() => {
    const defaults: Record<string, number> = {};
    for (const p of data.params ?? []) defaults[p.name] = p.default;
    paramValues = defaults;
  });

  // Redraw on param or data change
  $effect(() => {
    if (!canvas) return;
    drawPlot();
  });

  function drawPlot() {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, w, h);

    const [xMin, xMax] = data.xRange;
    const padding = 40;
    const plotW = w - padding * 2;
    const plotH = h - padding * 2;

    // Calculate points
    const points: [number, number][] = [];
    const steps = plotW;
    for (let i = 0; i <= steps; i++) {
      const x = xMin + (xMax - xMin) * (i / steps);
      try {
        const y = evaluate(data.expression, { ...paramValues, x });
        if (isFinite(y)) points.push([x, y]);
      } catch { /* skip bad point */ }
    }

    if (points.length === 0) return;

    // Y range
    const ys = points.map((p) => p[1]);
    let [yMin, yMax] = data.yRange ?? [Math.min(...ys), Math.max(...ys)];
    const yPad = (yMax - yMin) * 0.1 || 1;
    yMin -= yPad;
    yMax += yPad;

    function toCanvasX(x: number) { return padding + ((x - xMin) / (xMax - xMin)) * plotW; }
    function toCanvasY(y: number) { return padding + ((yMax - y) / (yMax - yMin)) * plotH; }

    // Background
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, w, h);

    // Grid
    if (data.showGrid !== false) {
      ctx.strokeStyle = '#2a2a2a';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 10; i++) {
        const x = xMin + (xMax - xMin) * (i / 10);
        const cx = toCanvasX(x);
        ctx.beginPath(); ctx.moveTo(cx, padding); ctx.lineTo(cx, h - padding); ctx.stroke();
      }
      for (let i = 0; i <= 8; i++) {
        const y = yMin + (yMax - yMin) * (i / 8);
        const cy = toCanvasY(y);
        ctx.beginPath(); ctx.moveTo(padding, cy); ctx.lineTo(w - padding, cy); ctx.stroke();
      }
    }

    // Axes
    ctx.strokeStyle = '#555';
    ctx.lineWidth = 1;
    if (yMin <= 0 && yMax >= 0) {
      const y0 = toCanvasY(0);
      ctx.beginPath(); ctx.moveTo(padding, y0); ctx.lineTo(w - padding, y0); ctx.stroke();
    }
    if (xMin <= 0 && xMax >= 0) {
      const x0 = toCanvasX(0);
      ctx.beginPath(); ctx.moveTo(x0, padding); ctx.lineTo(x0, h - padding); ctx.stroke();
    }

    // Curve
    ctx.strokeStyle = '#8b5cf6';
    ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    for (const [x, y] of points) {
      const cx = toCanvasX(x);
      const cy = toCanvasY(y);
      if (cy < -1000 || cy > h + 1000) { started = false; continue; }
      if (!started) { ctx.moveTo(cx, cy); started = true; }
      else ctx.lineTo(cx, cy);
    }
    ctx.stroke();

    // Axis labels
    ctx.fillStyle = '#666';
    ctx.font = '11px system-ui';
    ctx.textAlign = 'center';
    for (let i = 0; i <= 10; i += 2) {
      const x = xMin + (xMax - xMin) * (i / 10);
      ctx.fillText(x.toFixed(1), toCanvasX(x), h - padding + 15);
    }
    ctx.textAlign = 'right';
    for (let i = 0; i <= 8; i += 2) {
      const y = yMin + (yMax - yMin) * (i / 8);
      ctx.fillText(y.toFixed(1), padding - 5, toCanvasY(y) + 4);
    }
  }
</script>

{#if data.params?.length}
  <div class="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1 px-4 py-2">
    {#each data.params as param}
      <label class="text-xs space-y-0.5">
        <span class="opacity-50">{param.label ?? param.name}: <strong>{paramValues[param.name] ?? param.default}</strong></span>
        <input
          type="range"
          class="w-full accent-purple-500"
          min={param.min}
          max={param.max}
          step={param.step}
          bind:value={paramValues[param.name]}
        />
      </label>
    {/each}
  </div>
{/if}

<canvas bind:this={canvas} class="w-full" style="height: 300px;"></canvas>

<p class="text-center text-xs opacity-40 py-1.5">y = {data.expression}</p>
