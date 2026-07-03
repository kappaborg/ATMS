<script lang="ts">
  import type { FrameEvent } from "../lib/types";
  let { event }: { event: FrameEvent | undefined } = $props();

  const d = $derived(event?.decision);
  const sys = $derived(event?.system);
  const colour = (p?: string) =>
    p === "GREEN" ? "#2ecc71" : p === "YELLOW" ? "#f1c40f" : "#e74c3c";

  // Wire commanded_phase (ns_green / ew_green / all_red / *_yellow) -> label + colour.
  function wire(p: string | null | undefined): { label: string; c: string } {
    if (!p) return { label: "—", c: "#888" };
    if (p.endsWith("green")) return { label: `GREEN ${p.startsWith("ns") ? "N–S" : "E–W"}`, c: "#2ecc71" };
    if (p.endsWith("yellow")) return { label: `YELLOW ${p.startsWith("ns") ? "N–S" : "E–W"}`, c: "#f1c40f" };
    return { label: "ALL-RED", c: "#e74c3c" };
  }
  const cmd = $derived(wire(sys?.commanded_phase));
</script>

<section class="panel">
  {#if sys}
    <h2>Controller <span class="badge" class:stale={sys.stale}>{sys.stale ? "stale" : "live"}</span></h2>
    <div class="phase" style="--c:{cmd.c}">
      <div class="lamp"></div>
      <div>
        <div class="phase-name">{cmd.label}</div>
        <div class="dir">intersection {sys.intersection_id} · {sys.age_s}s ago</div>
      </div>
    </div>
    {#if sys.stale}
      <p class="uncal">⚠ No fresh command from the controller — it may have fallen back to fixed-time.</p>
    {/if}
    <p class="src">real decision-engine output. Panel estimate below.</p>
    <hr />
  {/if}
  <h2>{sys ? "Panel estimate" : "Decision"}</h2>
  {#if d}
    <div class="phase" style="--c:{colour(d.phase)}">
      <div class="lamp"></div>
      <div>
        <div class="phase-name">{d.phase}</div>
        <div class="dir">{d.active_direction.replace("_", "–")}</div>
      </div>
    </div>
    <dl>
      <dt>Priority</dt><dd>{d.priority}</dd>
      <dt>Confidence</dt><dd>{(d.confidence * 100).toFixed(0)}%</dd>
      <dt>Reason</dt><dd class="reason">{d.reason}</dd>
    </dl>

    {#if event?.approaches}
      <div class="approaches">
        <div class="appr" class:active={d.active_direction === "north_south"}>
          <span class="lbl">N–S</span>
          <span class="veh">{event.approaches.ns.vehicles} veh</span>
          <span class="spd">{event.calibrated ? event.approaches.ns.avg_speed_kmh.toFixed(0) + " km/h" : "—"}</span>
        </div>
        <div class="appr" class:active={d.active_direction === "east_west"}>
          <span class="lbl">E–W</span>
          <span class="veh">{event.approaches.ew.vehicles} veh</span>
          <span class="spd">{event.calibrated ? event.approaches.ew.avg_speed_kmh.toFixed(0) + " km/h" : "—"}</span>
        </div>
      </div>
      {#if !event.calibrated}
        <p class="uncal">⚠ uncalibrated — speeds unavailable, approaches split by frame centre. Calibrate this camera for real measurements.</p>
      {/if}
    {/if}

    <p class="note">Advisory only — the failsafe controller enforces signal safety.</p>
  {:else}
    <p class="empty">Waiting for a camera…</p>
  {/if}
</section>

<style>
  .panel { padding: 14px 16px; }
  h2 { margin: 0 0 12px; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.06em; color: #8b95a7; }
  .phase { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
  .lamp { width: 34px; height: 34px; border-radius: 50%; background: var(--c); box-shadow: 0 0 16px var(--c); }
  .phase-name { font-size: 1.3rem; font-weight: 700; color: var(--c); }
  .dir { font-size: 0.8rem; color: #9aa4b2; }
  dl { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; margin: 0; font-size: 0.85rem; }
  dt { color: #8b95a7; }
  dd { margin: 0; color: #dfe6ee; }
  .reason { font-size: 0.78rem; color: #b7c0cd; }
  .approaches { display: flex; gap: 8px; margin-top: 14px; }
  .appr { flex: 1; display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; background: #12151d; border: 1px solid #1e2230; border-radius: 6px; }
  .appr.active { border-color: #2ecc71; background: #12211a; }
  .appr .lbl { font-size: 0.72rem; color: #8b95a7; letter-spacing: 0.05em; }
  .appr .veh { font-size: 1.05rem; color: #eaf1f8; font-weight: 600; }
  .appr .spd { font-size: 0.78rem; color: #7fd1ff; }
  .uncal { margin: 8px 0 0; font-size: 0.68rem; color: #e0a94a; line-height: 1.35; }
  .note { margin-top: 14px; font-size: 0.7rem; color: #6b7688; line-height: 1.4; }
  .empty { color: #667; font-size: 0.85rem; }
  .badge { font-size: 0.6rem; padding: 2px 6px; border-radius: 10px; background: #12211a; color: #2ecc71; border: 1px solid #2ecc71; vertical-align: middle; text-transform: none; letter-spacing: 0; }
  .badge.stale { background: #241a12; color: #e0a94a; border-color: #e0a94a; }
  .src { margin: 8px 0 0; font-size: 0.68rem; color: #6b7688; }
  hr { border: none; border-top: 1px solid #1e2230; margin: 14px 0; }
</style>
