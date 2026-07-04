<script lang="ts">
  import type { FrameEvent, IntersectionInfo } from "../lib/types";

  let {
    intersections,
    events,
    onselect,
  }: {
    intersections: IntersectionInfo[];
    events: Record<string, FrameEvent>;
    onselect: (id: string) => void;
  } = $props();

  // Failsafe mode -> label + colour (mirrors DecisionPanel).
  function mode(m: string | null | undefined, reachable: boolean | undefined) {
    if (m === "ai_adaptive") return { label: "AI-ADAPTIVE", c: "#2ecc71" };
    if (m === "fixed_time") return { label: "FIXED-TIME", c: "#f1c40f" };
    if (m === "all_red_flash") return { label: "ALL-RED FLASH", c: "#e74c3c" };
    if (reachable === false) return { label: "CONTROLLER UNREACHABLE", c: "#7a8494" };
    return { label: "LOCAL ESTIMATE", c: "#4a90d9" };
  }

  // Aggregate live camera events for one intersection.
  function agg(cams: string[]) {
    let vehicles = 0, incidents = 0, streaming = 0;
    let preemption = false, pedestrian = false;
    let phase: string | null = null;
    for (const id of cams) {
      const e = events[id];
      if (!e) continue;
      streaming++;
      vehicles += e.counts?.vehicles ?? 0;
      incidents += e.incidents?.length ?? 0;
      if (e.preemption) preemption = true;
      if (e.pedestrian?.clearance_hold) pedestrian = true;
      if (!phase) phase = e.decision?.phase ?? null;
    }
    return { vehicles, incidents, streaming, preemption, pedestrian, phase };
  }

  const phaseColour = (p: string | null) =>
    p === "GREEN" ? "#2ecc71" : p === "YELLOW" ? "#f1c40f" : p === "ALL_RED" || p === "RED" ? "#e74c3c" : "#888";
</script>

<div class="grid">
  {#each intersections as it (it.intersection_id)}
    {@const a = agg(it.cameras)}
    {@const m = mode(it.system?.mode, it.system?.mode_reachable)}
    <button class="card" onclick={() => onselect(it.intersection_id)}
      class:alarm={it.system?.mode === "all_red_flash" || a.preemption}>
      <div class="mode" style="--c:{m.c}">{m.label}</div>
      <div class="id">Intersection {it.intersection_id}</div>
      <div class="phase">
        <span class="dot" style="background:{phaseColour(it.system?.commanded_phase ? null : a.phase)}"></span>
        {it.system?.commanded_phase ?? a.phase ?? "—"}
        {#if it.system?.stale}<span class="stale">STALE</span>{/if}
      </div>
      <div class="stats">
        <span>{a.streaming}/{it.cameras.length} cams</span>
        <span>🚗 {a.vehicles}</span>
      </div>
      <div class="alerts">
        {#if a.preemption}<span class="al red">🚨 preempt</span>{/if}
        {#if a.pedestrian}<span class="al amber">🚶 hold</span>{/if}
        {#if a.incidents > 0}<span class="al red">⚠ {a.incidents}</span>{/if}
      </div>
    </button>
  {:else}
    <div class="empty">No intersections — add a camera with an intersection ID.</div>
  {/each}
</div>

<style>
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; padding: 16px; align-content: start; overflow: auto; }
  .card {
    text-align: left; background: #0d0f14; border: 1px solid #1e2230; border-radius: 10px;
    padding: 14px; cursor: pointer; color: #dfe6ee; display: flex; flex-direction: column; gap: 8px;
    transition: border-color .15s;
  }
  .card:hover { border-color: #2b6ea3; }
  .card.alarm { border-color: #e74c3c; box-shadow: 0 0 14px rgba(231,76,60,0.4); }
  .mode { font-size: 0.66rem; font-weight: 700; letter-spacing: 0.04em; color: var(--c); }
  .id { font-size: 1.05rem; font-weight: 600; color: #eaf1f8; }
  .phase { display: flex; align-items: center; gap: 8px; font-size: 0.82rem; }
  .phase .dot { width: 10px; height: 10px; border-radius: 50%; }
  .phase .stale { font-size: 0.6rem; color: #e67e22; border: 1px solid #e67e22; border-radius: 3px; padding: 0 4px; }
  .stats { display: flex; gap: 12px; font-size: 0.76rem; color: #9aa4b2; }
  .alerts { display: flex; gap: 6px; flex-wrap: wrap; min-height: 18px; }
  .al { font-size: 0.66rem; padding: 1px 6px; border-radius: 4px; }
  .al.red { background: rgba(231,76,60,0.2); color: #ff8a7a; }
  .al.amber { background: rgba(243,156,18,0.2); color: #f0c674; }
  .empty { grid-column: 1/-1; color: #667; text-align: center; padding: 40px; }
</style>
