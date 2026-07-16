<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import type { FrameEvent, IntersectionInfo, CameraInfo } from "../lib/types";

  let {
    intersections,
    events,
    cameras,
    onselect,
  }: {
    intersections: IntersectionInfo[];
    events: Record<string, FrameEvent>;
    cameras: CameraInfo[];
    onselect: (id: string) => void;
  } = $props();

  const cssVar = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  // --- per-intersection live rollup from its cameras' latest frames ---
  type Node = { id: string; vehicles: number; phase: string; cong: number; cams: number; x: number; y: number };

  function phaseOf(id: string): string {
    const it = intersections.find((i) => i.intersection_id === id);
    const sys = it?.system;
    if (sys?.commanded_phase) return sys.commanded_phase;
    const camId = it?.cameras[0];
    return (camId && events[camId]?.decision.phase) || "GREEN";
  }
  function vehiclesOf(id: string): number {
    const it = intersections.find((i) => i.intersection_id === id);
    return (it?.cameras ?? []).reduce((s, c) => s + (events[c]?.counts.vehicles ?? 0), 0);
  }

  // deterministic ring layout (no geo coords in the data model)
  function layout(i: number, n: number): { x: number; y: number } {
    if (n <= 1) return { x: 50, y: 50 };
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    return { x: 50 + Math.cos(a) * 32, y: 50 + Math.sin(a) * 30 };
  }

  const nodes = $derived<Node[]>(
    intersections.map((it, i) => {
      const v = vehiclesOf(it.intersection_id);
      const pos = layout(i, intersections.length);
      return { id: it.intersection_id, vehicles: v, phase: phaseOf(it.intersection_id), cong: Math.min(1, v / 24), cams: it.cameras.length, x: pos.x, y: pos.y };
    }),
  );

  const congColor = (c: number) => (c > 0.66 ? "var(--color-critical)" : c > 0.4 ? "var(--color-warn)" : "var(--color-ok)");
  const phaseColor = (p: string) =>
    p === "GREEN" ? "var(--color-sig-green)" : p === "YELLOW" ? "var(--color-sig-amber)" : "var(--color-sig-red)";

  // --- KPIs ---
  // "Right now" figures must reflect only cameras that are currently live — a
  // camera that has gone offline keeps its last frame in `events`, so counting
  // raw events would freeze stale numbers into the network totals.
  const liveEvents = $derived(
    cameras.filter((c) => c.live).map((c) => events[c.camera_id]).filter((e): e is FrameEvent => !!e),
  );
  const totalVehicles = $derived(liveEvents.reduce((s, e) => s + e.counts.vehicles, 0));
  const liveCams = $derived(cameras.filter((c) => c.live).length);
  const incidents = $derived(liveEvents.reduce((s, e) => s + e.incidents.length + e.violations.length, 0));
  // Share of measured CO2 the adaptive-control model attributes to saved idling:
  // sum(est_saved_kg) / sum(total_co2_kg) across live cameras. Averaging
  // `savings_ratio` instead would only echo PANEL_ADAPTIVE_SAVINGS_RATIO, a
  // config constant that never moves with traffic.
  // null = nothing measured (emissions need a calibrated camera) — distinct
  // from 0%, which would claim we measured and found no saving.
  const co2Pct = $derived.by(() => {
    const es = liveEvents.map((e) => e.emissions).filter((x): x is NonNullable<typeof x> => !!x);
    const total = es.reduce((s, e) => s + e.total_co2_kg, 0);
    if (!es.length || total <= 0) return null;
    return Math.round((es.reduce((s, e) => s + e.est_saved_kg, 0) / total) * 100);
  });

  const busyCount = $derived(nodes.filter((n) => n.cong > 0.66).length);

  // --- live time-series (sampled once a second, kept to 40 points) ---
  let flow = $state<number[]>(Array(40).fill(0));
  let clean = $state<number[]>(Array(40).fill(0));
  let flowCanvas = $state<HTMLCanvasElement>();
  let cleanCanvas = $state<HTMLCanvasElement>();

  function drawChart(cv: HTMLCanvasElement | undefined, data: number[], colorVar: string) {
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = cv.clientWidth;
    const h = cv.clientHeight;
    cv.width = w * dpr;
    cv.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const col = cssVar(colorVar);
    const grid = cssVar("--color-border");
    let min = Math.min(...data);
    let max = Math.max(...data);
    const pad = (max - min) * 0.25 || 1;
    min -= pad;
    max += pad;
    const X = (i: number) => (i / (data.length - 1)) * w;
    const Y = (v: number) => h - ((v - min) / (max - min)) * (h - 6) - 3;
    ctx.strokeStyle = grid;
    ctx.lineWidth = 1;
    for (let g = 1; g < 4; g++) {
      const yy = (h / 4) * g + 0.5;
      ctx.beginPath();
      ctx.moveTo(0, yy);
      ctx.lineTo(w, yy);
      ctx.stroke();
    }
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, col + "3a");
    grad.addColorStop(1, col + "00");
    ctx.beginPath();
    ctx.moveTo(0, Y(data[0]));
    for (let i = 1; i < data.length; i++) ctx.lineTo(X(i), Y(data[i]));
    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(0, Y(data[0]));
    for (let i = 1; i < data.length; i++) ctx.lineTo(X(i), Y(data[i]));
    ctx.strokeStyle = col;
    ctx.lineWidth = 2.2;
    ctx.lineJoin = "round";
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(X(data.length - 1), Y(data[data.length - 1]), 3.2, 0, 7);
    ctx.fillStyle = col;
    ctx.fill();
  }

  function redraw() {
    drawChart(flowCanvas, flow, "--color-accent");
    drawChart(cleanCanvas, clean, "--color-ok");
  }

  let timer: ReturnType<typeof setInterval>;
  onMount(() => {
    timer = setInterval(() => {
      const es = liveEvents;
      const veh = es.reduce((s, e) => s + e.counts.vehicles, 0);
      const co2 = es.reduce((s, e) => s + (e.emissions?.rate_kg_h ?? 0), 0);
      flow = [...flow.slice(1), veh];
      clean = [...clean.slice(1), co2];
      redraw();
    }, 1000);
    redraw();
    window.addEventListener("resize", redraw);
  });
  onDestroy(() => {
    clearInterval(timer);
    window.removeEventListener("resize", redraw);
  });
</script>

<div class="ov">
  <!-- header -->
  <div class="welcome">
    <div class="wt">
      <div class="greet">Network overview</div>
      <div class="wsub">
        {#if intersections.length}
          Monitoring <b>{intersections.length} {intersections.length === 1 ? "junction" : "junctions"}</b> —
          {#if busyCount}<b>{busyCount}</b> under heavy load{:else}traffic flowing normally{/if}{#if incidents}, <span class="alert">{incidents} need attention</span>{/if}.
        {:else}
          No junctions online yet — add a camera to start monitoring.
        {/if}
      </div>
    </div>
  </div>

  <!-- KPIs -->
  <div class="kpis">
    <div class="kpi"><div class="k"><span class="label">Vehicles right now</span></div><div class="v num">{totalVehicles}</div><div class="d muted">across the network</div></div>
    <div class="kpi"><div class="k"><span class="label">Cameras live</span></div><div class="v num">{liveCams}<u>/{cameras.length}</u></div><div class="d muted">feeding detections</div></div>
    <div class="kpi"><div class="k"><span class="label">CO₂ saved</span></div>{#if co2Pct === null}<div class="v num dim">—</div><div class="d muted">needs a calibrated camera</div>{:else}<div class="v num">{co2Pct}<u>%</u></div><div class="d ok">less idling vs fixed timers</div>{/if}</div>
    <div class="kpi"><div class="k"><span class="label">Needs attention</span></div><div class="v num">{incidents}</div><div class="d" class:warn={incidents > 0}>{incidents ? "active incidents" : "all clear"}</div></div>
  </div>

  <!-- map + charts -->
  <div class="grid">
    <section class="panel map-panel">
      <div class="ph"><span class="t">Junction map</span><span class="u">live · click to open</span></div>
      <div class="body">
        <div class="map-wrap">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" class="map">
            {#each nodes as n (n.id)}
              {#each nodes.slice(nodes.indexOf(n) + 1) as m}
                <line x1={n.x} y1={n.y} x2={m.x} y2={m.y} stroke="var(--color-border-2)" stroke-width="0.4" />
              {/each}
            {/each}
            {#each nodes as n (n.id)}
              <g class="mnode" role="button" tabindex="0" onclick={() => onselect(n.id)} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && onselect(n.id)}>
                <circle cx={n.x} cy={n.y} r={2.4 + n.cong * 2.4} fill={congColor(n.cong)} fill-opacity="0.18" />
                <circle cx={n.x} cy={n.y} r="1.8" fill={congColor(n.cong)} stroke="var(--color-surface-1)" stroke-width="0.6" />
                <circle cx={n.x} cy={n.y - 4.6} r="0.9" fill={phaseColor(n.phase)} />
              </g>
            {/each}
          </svg>
          {#each nodes as n (n.id)}
            <button class="mlabel" style="left:{n.x}%;top:{n.y}%" onclick={() => onselect(n.id)}>
              <b>Int {n.id}</b><span>{n.vehicles} veh</span>
            </button>
          {/each}
          {#if !nodes.length}<div class="mempty">No junctions to map yet.</div>{/if}
        </div>
        <div class="legend">
          <span class="it"><i style="background:var(--color-ok)"></i>flowing</span>
          <span class="it"><i style="background:var(--color-warn)"></i>busy</span>
          <span class="it"><i style="background:var(--color-critical)"></i>heavy</span>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="ph"><span class="t">Traffic flow</span><span class="u">vehicles tracked · live</span></div>
      <div class="body"><div class="chart-wrap"><canvas bind:this={flowCanvas}></canvas></div>
        <div class="legend"><span class="it"><i class="ln" style="background:var(--color-accent)"></i>across the network</span></div>
      </div>
    </section>

    <section class="panel">
      <div class="ph"><span class="t">Emissions avoided</span><span class="u">CO₂ saved · kg/h</span></div>
      <div class="body"><div class="chart-wrap"><canvas bind:this={cleanCanvas}></canvas></div>
        <div class="legend"><span class="it"><i class="ln" style="background:var(--color-ok)"></i>emissions avoided</span></div>
      </div>
    </section>
  </div>
</div>

<style>
  .ov { padding: 18px; }
  .num { font-variant-numeric: tabular-nums; }
  .label { font-size: 11.5px; font-weight: 600; color: var(--color-dim); }
  .muted { color: var(--color-muted); } .ok { color: var(--color-ok); } .warn { color: var(--color-warn); } .dim { color: var(--color-dim); }

  .welcome { display: flex; align-items: center; gap: 16px; padding: 16px 20px; margin-bottom: 16px;
    border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: var(--sh-1);
    background: var(--color-surface-1); }
  .greet { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; }
  .wsub { font-size: 13.5px; color: var(--color-muted); margin-top: 3px; line-height: 1.5; }
  .wsub b { color: var(--color-text); font-weight: 600; } .wsub .alert { color: var(--color-warn); font-weight: 600; }

  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px; }
  .kpi { background: var(--color-surface-1); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 15px 17px; box-shadow: var(--sh-1); }
  .kpi .k { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .kpi .v { font-size: 26px; font-weight: 750; letter-spacing: -0.02em; } .kpi .v u { text-decoration: none; font-size: 13px; color: var(--color-dim); margin-left: 2px; font-weight: 600; }
  .kpi .d { font-size: 12px; margin-top: 4px; font-weight: 550; color: var(--color-muted); }

  .grid { display: grid; grid-template-columns: 1.4fr 1fr; grid-template-rows: auto auto; gap: 16px; }
  .panel { background: var(--color-surface-1); border: 1px solid var(--color-border); border-radius: var(--radius-lg); display: flex; flex-direction: column; overflow: hidden; box-shadow: var(--sh-1); }
  .map-panel { grid-row: span 2; }
  .panel .ph { display: flex; align-items: center; gap: 10px; padding: 13px 16px; border-bottom: 1px solid var(--color-border); }
  .panel .ph .t { font-size: 13.5px; font-weight: 650; } .panel .ph .u { font-size: 11.5px; color: var(--color-muted); margin-left: auto; }
  .panel .body { padding: 14px 16px; flex: 1; min-height: 0; display: flex; flex-direction: column; }

  .map-wrap { position: relative; flex: 1; min-height: 320px; border-radius: var(--radius); overflow: hidden; background: var(--color-surface-2); }
  .map { width: 100%; height: 100%; display: block; }
  .mnode { cursor: pointer; }
  .mlabel { position: absolute; transform: translate(-50%, 10px); background: color-mix(in srgb, var(--color-surface-1) 82%, transparent); backdrop-filter: blur(4px);
    border: 1px solid var(--color-border); border-radius: 100px; padding: 3px 9px; display: flex; gap: 6px; align-items: baseline; cursor: pointer; box-shadow: var(--sh-1); }
  .mlabel b { font-size: 11.5px; font-weight: 650; } .mlabel span { font-size: 10.5px; color: var(--color-muted); font-variant-numeric: tabular-nums; }
  .mempty { position: absolute; inset: 0; display: grid; place-items: center; color: var(--color-dim); font-size: 13px; }

  .chart-wrap { position: relative; height: 150px; } .chart-wrap canvas { width: 100%; height: 100%; display: block; }
  .legend { display: flex; gap: 15px; margin-top: 10px; }
  .legend .it { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--color-muted); }
  .legend .it i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; } .legend .it i.ln { width: 13px; height: 4px; border-radius: 2px; }

  @media (max-width: 1024px) {
    .kpis { grid-template-columns: repeat(2, 1fr); }
    .grid { grid-template-columns: 1fr; }
    .map-panel { grid-row: auto; }
  }
  @media (max-width: 560px) {
    .kpis { grid-template-columns: 1fr; }
  }
</style>
