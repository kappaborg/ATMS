<script lang="ts">
  import type { FrameEvent } from "../lib/types";
  import { setPreemption } from "../lib/gateway";
  let {
    event,
    camera_id = null,
    canOperate = false,
  }: { event: FrameEvent | undefined; camera_id?: string | null; canOperate?: boolean } = $props();

  let preemptErr = $state("");
  async function preempt(direction: "north_south" | "east_west", active: boolean) {
    preemptErr = "";
    if (!camera_id) return;
    try {
      await setPreemption(camera_id, direction, active);
    } catch (e) {
      preemptErr = e instanceof Error ? e.message : "failed";
    }
  }

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

  // Failsafe mode — the top-line safety signal.
  function modeInfo(m: string | null | undefined, reachable: boolean | undefined) {
    if (!reachable || !m) return { label: "controller unreachable", c: "#8b95a7", alarm: false };
    if (m === "ai_adaptive") return { label: "AI ADAPTIVE", c: "#2ecc71", alarm: false };
    if (m === "fixed_time") return { label: "FIXED-TIME (AI degraded)", c: "#f1c40f", alarm: false };
    if (m === "all_red_flash") return { label: "ALL-RED FLASH", c: "#e74c3c", alarm: true };
    return { label: m, c: "#8b95a7", alarm: false };
  }
  const mode = $derived(modeInfo(sys?.mode, sys?.mode_reachable));
</script>

<section class="panel">
  {#if sys}
    {#if sys.mode !== undefined}
      <div class="mode" class:alarm={mode.alarm} style="--mc:{mode.c}">
        <span class="mdot"></span>
        <div>
          <div class="mlabel">{mode.label}</div>
          <div class="msub">failsafe mode</div>
        </div>
      </div>
    {/if}
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
  {#if event?.preemption}
    <div class="preempt-banner">🚨 EMERGENCY PREEMPTION ACTIVE — {event.preemption === "north_south" ? "N–S" : "E–W"} cleared</div>
  {/if}
  {#if canOperate && camera_id}
    <div class="preempt-ctl">
      <span>🚨 Emergency preempt</span>
      <div class="pbtns">
        <button class:on={event?.preemption === "north_south"} onclick={() => preempt("north_south", event?.preemption !== "north_south")}>N–S</button>
        <button class:on={event?.preemption === "east_west"} onclick={() => preempt("east_west", event?.preemption !== "east_west")}>E–W</button>
        {#if event?.preemption}<button class="clear" onclick={() => preempt(event!.preemption!, false)}>Clear</button>{/if}
      </div>
    </div>
    {#if preemptErr}<p class="perr">{preemptErr}</p>{/if}
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

    {#if event?.emissions}
      <div class="carbon">
        <div class="chead">🌱 Emissions <span>this session</span></div>
        <div class="cgrid">
          <div class="cm"><b>{event.emissions.total_co2_kg.toFixed(2)}<i>kg</i></b><span>CO₂ measured</span></div>
          <div class="cm"><b>{event.emissions.rate_kg_h.toFixed(1)}<i>kg/h</i></b><span>rate</span></div>
          <div class="cm"><b>{event.emissions.avg_g_per_km.toFixed(0)}<i>g/km</i></b><span>avg intensity</span></div>
          <div class="cm saved"><b>{event.emissions.est_saved_kg.toFixed(2)}<i>kg</i></b><span>est. saved</span></div>
        </div>
        <p class="cnote">Est. saved = measured idle CO₂ × {(event.emissions.savings_ratio * 100).toFixed(0)}% (adaptive-control model; adjustable).</p>
      </div>
    {:else if event && !event.calibrated}
      <p class="cuncal">🌱 Calibrate this camera to measure CO₂ emissions (needs real speed).</p>
    {/if}

    {#if d.predicted_congestion}
      <div class="forecast">
        <div class="fhead">🔮 Congestion forecast <span>{d.predicted_congestion.horizon_min} min ahead</span></div>
        <div class="fbars">
          <div class="fbar"><span class="flbl">N–S</span><div class="track"><div class="fill" style="width:{Math.round(d.predicted_congestion.north_south * 100)}%"></div></div><span class="fpct">{Math.round(d.predicted_congestion.north_south * 100)}%</span></div>
          <div class="fbar"><span class="flbl">E–W</span><div class="track"><div class="fill" style="width:{Math.round(d.predicted_congestion.east_west * 100)}%"></div></div><span class="fpct">{Math.round(d.predicted_congestion.east_west * 100)}%</span></div>
        </div>
      </div>
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
  .preempt-banner {
    margin: 10px 16px 0; padding: 8px 12px; border-radius: 6px; text-align: center;
    background: #e74c3c; color: #fff; font-weight: 700; font-size: 0.8rem;
    animation: ppulse 1s ease-in-out infinite; box-shadow: 0 0 16px rgba(231,76,60,0.7);
  }
  @keyframes ppulse { 0%,100% { opacity: 1; } 50% { opacity: 0.65; } }
  .preempt-ctl { display: flex; align-items: center; justify-content: space-between; margin: 10px 16px 0; padding: 8px 12px; background: #1a1113; border: 1px solid #3a1c1c; border-radius: 8px; font-size: 0.74rem; color: #e6a4a4; }
  .preempt-ctl .pbtns { display: flex; gap: 6px; }
  .preempt-ctl button { background: #2a1618; border: 1px solid #5a2b2b; color: #f0c4c4; border-radius: 5px; padding: 4px 10px; cursor: pointer; font-size: 0.74rem; }
  .preempt-ctl button.on { background: #e74c3c; color: #fff; border-color: #e74c3c; }
  .preempt-ctl button.clear { border-color: #2b3547; color: #9aa4b2; background: none; }
  .perr { margin: 6px 16px 0; color: #e74c3c; font-size: 0.72rem; }
  .carbon { margin-top: 14px; padding: 10px 12px; background: #0d1a12; border: 1px solid #1c3a28; border-radius: 8px; }
  .chead { font-size: 0.74rem; color: #7fd6a0; margin-bottom: 8px; }
  .chead span { color: #5a7566; }
  .cgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .cm { display: flex; flex-direction: column; }
  .cm b { font-size: 1.0rem; color: #eaf1f8; }
  .cm b i { font-size: 0.6rem; color: #7a8494; font-style: normal; margin-left: 2px; }
  .cm span { font-size: 0.62rem; color: #7a8494; text-transform: uppercase; letter-spacing: 0.03em; }
  .cm.saved b { color: #2ecc71; }
  .cnote { margin: 8px 0 0; font-size: 0.64rem; color: #6b7688; line-height: 1.35; }
  .cuncal { margin-top: 14px; font-size: 0.72rem; color: #7fd6a0; }
  .forecast { margin-top: 14px; padding: 10px 12px; background: #0e1622; border: 1px solid #1e2230; border-radius: 8px; }
  .fhead { font-size: 0.74rem; color: #9aa4b2; margin-bottom: 8px; }
  .fhead span { color: #6b7688; }
  .fbars { display: flex; flex-direction: column; gap: 6px; }
  .fbar { display: grid; grid-template-columns: 34px 1fr 36px; gap: 8px; align-items: center; }
  .fbar .flbl { font-size: 0.72rem; color: #8b95a7; }
  .fbar .track { height: 8px; background: #1a2331; border-radius: 4px; overflow: hidden; }
  .fbar .fill { height: 100%; background: linear-gradient(90deg,#2b6ea3,#7fd1ff); }
  .fbar .fpct { font-size: 0.72rem; color: #cfe8ff; text-align: right; }
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
  .mode { display: flex; align-items: center; gap: 10px; padding: 10px 12px; margin-bottom: 14px; border-radius: 8px; background: color-mix(in srgb, var(--mc) 12%, #0b0d12); border: 1px solid var(--mc); }
  .mode.alarm { animation: pulse 1s ease-in-out infinite; }
  .mode .mdot { width: 12px; height: 12px; border-radius: 50%; background: var(--mc); box-shadow: 0 0 10px var(--mc); }
  .mode .mlabel { font-size: 0.95rem; font-weight: 700; color: var(--mc); letter-spacing: 0.02em; }
  .mode .msub { font-size: 0.62rem; color: #8b95a7; text-transform: uppercase; letter-spacing: 0.06em; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }
</style>
