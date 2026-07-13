<script lang="ts">
  import type { Corridor } from "../lib/types";
  let { corridor }: { corridor: Corridor } = $props();

  // Diagram geometry. x = time (two cycles), y = distance along the corridor
  // (0 at bottom). Green bands cascade; the diagonal design-speed line rides
  // through them — that's the green wave.
  const W = 340, H = 200, ml = 34, mr = 8, mt = 10, mb = 22;
  const tMax = $derived(corridor.cycle_s * 2);
  const dMax = $derived(Math.max(corridor.length_m, 1));
  const x = (t: number) => ml + (t / tMax) * (W - ml - mr);
  const y = (d: number) => H - mb - (d / dMax) * (H - mt - mb);
</script>

<svg viewBox="0 0 {W} {H}" class="tsd">
  <!-- axes -->
  <line x1={ml} y1={mt} x2={ml} y2={H - mb} class="axis" />
  <line x1={ml} y1={H - mb} x2={W - mr} y2={H - mb} class="axis" />
  <text x={2} y={mt + 8} class="lbl">dist</text>
  <text x={W - mr - 20} y={H - 6} class="lbl">time</text>

  <!-- green bands per intersection -->
  {#each corridor.bands as b}
    {#each b.windows as w}
      <rect x={x(w[0])} y={y(b.distance_m) - 4} width={x(w[1]) - x(w[0])} height="8" class="green" />
    {/each}
    <text x={4} y={y(b.distance_m) + 3} class="itag">#{b.intersection_id}</text>
  {/each}

  <!-- design-speed vehicle trajectory (rides the wave) -->
  <line x1={x(corridor.trajectory[0][0])} y1={y(corridor.trajectory[0][1])}
        x2={x(corridor.trajectory[1][0])} y2={y(corridor.trajectory[1][1])} class="veh" />
</svg>
<p class="cap">{corridor.design_speed_kmh} km/h design · {corridor.cycle_s}s cycle · {corridor.length_m} m ·
  {corridor.direction === "north_south" ? "N–S" : "E–W"}</p>

<style>
  .tsd { width: 100%; height: auto; background: var(--color-surface-1); border: 1px solid var(--color-border); border-radius: 8px; }
  .axis { stroke: var(--color-border-2); stroke-width: 1; }
  .green { fill: color-mix(in srgb, var(--color-sig-green) 70%, transparent); }
  .veh { stroke: var(--color-accent); stroke-width: 2; stroke-dasharray: 4 3; }
  .lbl { fill: var(--color-dim); font-size: 8px; }
  .itag { fill: var(--color-muted); font-size: 8px; }
  .cap { margin: 4px 2px 0; font-size: 0.66rem; color: var(--color-muted); }
</style>
