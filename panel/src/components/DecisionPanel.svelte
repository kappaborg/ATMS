<script lang="ts">
  import type { FrameEvent } from "../lib/types";
  import { setPreemption, type HistoryTotals } from "../lib/gateway";
  import Icon from "./Icon.svelte";
  let {
    event,
    camera_id = null,
    canOperate = false,
    history30 = null,
  }: { event: FrameEvent | undefined; camera_id?: string | null; canOperate?: boolean; history30?: HistoryTotals | null } = $props();

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

  // Session CO2 totals are routinely far below 1 kg — a car crossing a ~50 m
  // field of view at 40 km/h accrues ~7 g — so a fixed 2-decimal kg rendering
  // collapses real readings to "0.00". The gateway keeps 4 decimals (emissions.py)
  // precisely so the UI can show them; drop to grams under 1 kg.
  function mass(kg: number): { v: string; unit: string } {
    if (kg >= 1) return { v: kg.toFixed(2), unit: "kg" };
    const g = kg * 1000;
    return { v: g < 10 ? g.toFixed(1) : g.toFixed(0), unit: "g" };
  }
  const co2Total = $derived(event?.emissions ? mass(event.emissions.total_co2_kg) : null);
  const co2Rate = $derived(event?.emissions ? mass(event.emissions.rate_kg_h) : null);
  const co2Saved = $derived(event?.emissions ? mass(event.emissions.est_saved_kg) : null);

  const d = $derived(event?.decision);
  const sys = $derived(event?.system);
  const colour = (p?: string) =>
    p === "GREEN" ? "var(--color-sig-green)" : p === "YELLOW" ? "var(--color-sig-amber)" : "var(--color-sig-red)";

  // Wire commanded_phase (ns_green / ew_green / all_red / *_yellow) -> label + colour.
  function wire(p: string | null | undefined): { label: string; c: string } {
    if (!p) return { label: "—", c: "var(--color-dim)" };
    if (p.endsWith("green")) return { label: `GREEN ${p.startsWith("ns") ? "N–S" : "E–W"}`, c: "var(--color-sig-green)" };
    if (p.endsWith("yellow")) return { label: `YELLOW ${p.startsWith("ns") ? "N–S" : "E–W"}`, c: "var(--color-sig-amber)" };
    return { label: "ALL-RED", c: "var(--color-sig-red)" };
  }
  const cmd = $derived(wire(sys?.commanded_phase));

  // Failsafe mode — the top-line safety signal.
  function modeInfo(m: string | null | undefined, reachable: boolean | undefined) {
    if (!reachable || !m) return { label: "controller unreachable", c: "var(--color-muted)", alarm: false };
    if (m === "ai_adaptive") return { label: "AI ADAPTIVE", c: "var(--color-ok)", alarm: false };
    if (m === "fixed_time") return { label: "FIXED-TIME (AI degraded)", c: "var(--color-warn)", alarm: false };
    if (m === "all_red_flash") return { label: "ALL-RED FLASH", c: "var(--color-critical)", alarm: true };
    return { label: m, c: "var(--color-muted)", alarm: false };
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
      <p class="uncal"><Icon name="warning" size={13} />No fresh command from the controller — it may have fallen back to fixed-time.</p>
    {/if}
    <p class="src">real decision-engine output. Panel estimate below.</p>
    <hr />
  {/if}
  {#if event?.preemption}
    <div class="preempt-banner"><Icon name="siren" size={15} stroke={2} />EMERGENCY PREEMPTION ACTIVE — {event.preemption === "north_south" ? "N–S" : "E–W"} cleared</div>
  {:else if event?.emergency_vehicle}
    <div class="ev-banner">
      <Icon name="siren" size={15} stroke={2} />EMERGENCY VEHICLE DETECTED — {event.emergency_vehicle.direction === "north_south" ? "N–S" : "E–W"} (flashing lights)
      {#if canOperate && camera_id}
        <button onclick={() => preempt(event!.emergency_vehicle!.direction, true)}>Preempt {event.emergency_vehicle.direction === "north_south" ? "N–S" : "E–W"}</button>
      {/if}
    </div>
  {/if}
  {#if event?.pedestrian?.clearance_hold}
    <div class="ped-banner"><Icon name="pedestrian" size={14} stroke={2} />Holding all-red — pedestrian in crossing</div>
  {:else if event?.pedestrian?.present}
    <div class="ped-note"><Icon name="pedestrian" size={13} />Pedestrian detected in roadway</div>
  {/if}
  {#if canOperate && camera_id}
    <div class="preempt-ctl">
      <span><Icon name="siren" size={13} />Emergency preempt</span>
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
          <span class="lbl">N–S {#if event.transit?.ns}<span class="bus" title="Transit priority — bus present"><Icon name="bus" size={13} /></span>{/if}</span>
          <span class="veh">{event.approaches.ns.vehicles} veh</span>
          <span class="spd">{event.calibrated ? event.approaches.ns.avg_speed_kmh.toFixed(0) + " km/h" : "—"}</span>
        </div>
        <div class="appr" class:active={d.active_direction === "east_west"}>
          <span class="lbl">E–W {#if event.transit?.ew}<span class="bus" title="Transit priority — bus present"><Icon name="bus" size={13} /></span>{/if}</span>
          <span class="veh">{event.approaches.ew.vehicles} veh</span>
          <span class="spd">{event.calibrated ? event.approaches.ew.avg_speed_kmh.toFixed(0) + " km/h" : "—"}</span>
        </div>
      </div>
      {#if !event.calibrated}
        <p class="uncal"><Icon name="warning" size={13} />uncalibrated — speeds unavailable, approaches split by frame centre. Calibrate this camera for real measurements.</p>
      {/if}
    {/if}

    {#if event?.emissions}
      <div class="carbon">
        <div class="chead"><Icon name="leaf" size={13} />Emissions <span>this session</span></div>
        <div class="cgrid">
          <div class="cm"><b>{co2Total?.v}<i>{co2Total?.unit}</i></b><span>CO₂ measured</span></div>
          <div class="cm"><b>{co2Rate?.v}<i>{co2Rate?.unit}/h</i></b><span>rate</span></div>
          <div class="cm"><b>{event.emissions.avg_g_per_km.toFixed(0)}<i>g/km</i></b><span>avg intensity</span></div>
          <div class="cm saved"><b>{co2Saved?.v}<i>{co2Saved?.unit}</i></b><span>est. saved</span></div>
        </div>
        <p class="cnote">Est. saved = measured idle CO₂ × {(event.emissions.savings_ratio * 100).toFixed(0)}% (adaptive-control model, set in the gateway config — an estimate, not a measurement).</p>
      </div>
    {:else if event && !event.calibrated}
      <p class="cuncal"><Icon name="leaf" size={13} />Calibrate this camera to measure CO₂ emissions (needs real speed).</p>
    {:else if event}
      <!-- Calibrated, but the gateway has measured nothing yet (no moving vehicle
           seen since the worker started), so `emissions` is null rather than 0. -->
      <p class="cuncal"><Icon name="leaf" size={13} />No emissions measured yet — waiting for the first vehicle.</p>
    {/if}

    {#if history30 && history30.vehicles > 0}
      <div class="hist">
        <div class="hhead"><Icon name="chart" size={13} />Persisted history <span>last 30 days</span></div>
        <div class="hrow">
          <b>{history30.vehicles.toLocaleString()}</b> vehicles ·
          <b>{history30.saved_kg.toFixed(1)} kg</b> CO₂ saved ·
          <b>{history30.incidents}</b> incidents
        </div>
      </div>
    {/if}

    {#if d.predicted_congestion}
      <div class="forecast">
        <div class="fhead"><Icon name="forecast" size={13} />Congestion forecast <span>{d.predicted_congestion.horizon_min} min ahead</span></div>
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
  /* icons sit on the text baseline everywhere in this panel */
  .panel :global(svg) { flex: none; vertical-align: -0.15em; }
  h2 { margin: 0 0 12px; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-muted); }
  .phase { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
  .lamp { width: 34px; height: 34px; border-radius: 50%; background: var(--c); box-shadow: 0 0 16px var(--c); }
  .phase-name { font-size: 1.3rem; font-weight: 700; color: var(--c); }
  .dir { font-size: 0.8rem; color: var(--color-muted); }
  dl { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; margin: 0; font-size: 0.85rem; }
  dt { color: var(--color-muted); }
  dd { margin: 0; color: var(--color-text); }
  /* Reserve two lines so a 1↔2 line reason never shifts the rows below it. */
  .reason { font-size: 0.78rem; color: var(--color-muted); line-height: 1.4; min-height: 2.24rem; }
  .preempt-banner {
    margin: 10px 16px 0; padding: 8px 12px; border-radius: var(--radius-sm); text-align: center;
    background: var(--color-critical); color: #fff; font-weight: 700; font-size: 0.8rem;
    animation: ppulse 1s ease-in-out infinite;
  }
  .ped-banner {
    margin: 10px 16px 0; padding: 8px 12px; border-radius: var(--radius-sm); text-align: center;
    background: var(--color-warn); color: #1a1206; font-weight: 700; font-size: 0.78rem;
    animation: ppulse 1.1s ease-in-out infinite;
  }
  .ped-note { margin: 10px 16px 0; padding: 6px 12px; border-radius: 6px; background: var(--color-surface-2); color: var(--color-warn); font-size: 0.74rem; text-align: center; }
  @keyframes ppulse { 0%,100% { opacity: 1; } 50% { opacity: 0.65; } }
  .ev-banner {
    margin: 10px 16px 0; padding: 8px 12px; border-radius: var(--radius-sm); text-align: center;
    background: var(--color-accent); color: #fff; font-weight: 700; font-size: 0.78rem;
    animation: ppulse 0.8s ease-in-out infinite;
    display: flex; align-items: center; justify-content: center; gap: 10px; flex-wrap: wrap;
  }
  /* fixed white button on the solid-blue safety banner — dark-blue text stays legible in both themes */
  .ev-banner button { background: #fff; color: #1f52c0; border: none; border-radius: 5px; padding: 4px 12px; font-weight: 700; cursor: pointer; font-size: 0.76rem; }
  .preempt-ctl { display: flex; align-items: center; justify-content: space-between; margin: 10px 16px 0; padding: 8px 12px; background: var(--color-surface-1); border: 1px solid var(--color-border-2); border-radius: 8px; font-size: 0.74rem; color: var(--color-critical); }
  .preempt-ctl .pbtns { display: flex; gap: 6px; }
  .preempt-ctl button { background: var(--color-surface-2); border: 1px solid var(--color-border-2); color: var(--color-critical); border-radius: 5px; padding: 4px 10px; cursor: pointer; font-size: 0.74rem; }
  .preempt-ctl button.on { background: var(--color-critical); color: #fff; border-color: var(--color-critical); }
  .preempt-ctl button.clear { border-color: var(--color-border-2); color: var(--color-muted); background: none; }
  .perr { margin: 6px 16px 0; color: var(--color-critical); font-size: 0.72rem; }
  .carbon { margin-top: 14px; padding: 10px 12px; background: var(--color-surface-1); border: 1px solid var(--color-border-2); border-radius: 8px; }
  .chead { font-size: 0.74rem; color: var(--color-ok); margin-bottom: 8px; }
  .chead span { color: var(--color-dim); }
  .cgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .cm { display: flex; flex-direction: column; }
  .cm b { font-size: 1.0rem; color: var(--color-text); }
  .cm b i { font-size: 0.6rem; color: var(--color-dim); font-style: normal; margin-left: 2px; }
  .cm span { font-size: 0.62rem; color: var(--color-dim); text-transform: uppercase; letter-spacing: 0.03em; }
  .cm.saved b { color: var(--color-ok); }
  .cnote { margin: 8px 0 0; font-size: 0.64rem; color: var(--color-dim); line-height: 1.35; }
  .cuncal { margin-top: 14px; font-size: 0.72rem; color: var(--color-ok); }
  .hist { margin-top: 10px; padding: 8px 12px; background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: 8px; }
  .hhead { font-size: 0.72rem; color: var(--color-muted); margin-bottom: 4px; }
  .hhead span { color: var(--color-dim); }
  .hrow { font-size: 0.74rem; color: var(--color-text); }
  .hrow b { color: var(--color-text); }
  .forecast { margin-top: 14px; padding: 10px 12px; background: var(--color-surface-3); border: 1px solid var(--color-border); border-radius: 8px; }
  .fhead { font-size: 0.74rem; color: var(--color-muted); margin-bottom: 8px; }
  .fhead span { color: var(--color-dim); }
  .fbars { display: flex; flex-direction: column; gap: 6px; }
  .fbar { display: grid; grid-template-columns: 34px 1fr 36px; gap: 8px; align-items: center; }
  .fbar .flbl { font-size: 0.72rem; color: var(--color-muted); }
  .fbar .track { height: 8px; background: var(--color-surface-2); border-radius: 4px; overflow: hidden; }
  .fbar .fill { height: 100%; background: var(--color-accent); }
  .fbar .fpct { font-size: 0.72rem; color: var(--color-accent-dim); text-align: right; }
  .approaches { display: flex; gap: 8px; margin-top: 14px; }
  .appr { flex: 1; display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: 6px; }
  .appr.active { border-color: var(--color-ok); background: var(--color-surface-2); }
  .appr .lbl { font-size: 0.72rem; color: var(--color-muted); letter-spacing: 0.05em; }
  .appr .veh { font-size: 1.05rem; color: var(--color-text); font-weight: 600; }
  .appr .spd { font-size: 0.78rem; color: var(--color-accent-dim); }
  .uncal { margin: 8px 0 0; font-size: 0.68rem; color: var(--color-warn); line-height: 1.35; }
  .note { margin-top: 14px; font-size: 0.7rem; color: var(--color-dim); line-height: 1.4; }
  .empty { color: var(--color-dim); font-size: 0.85rem; }
  .badge { font-size: 0.6rem; padding: 2px 6px; border-radius: 10px; background: var(--color-surface-2); color: var(--color-ok); border: 1px solid var(--color-ok); vertical-align: middle; text-transform: none; letter-spacing: 0; }
  .badge.stale { background: var(--color-surface-2); color: var(--color-warn); border-color: var(--color-warn); }
  .src { margin: 8px 0 0; font-size: 0.68rem; color: var(--color-dim); }
  hr { border: none; border-top: 1px solid var(--color-border); margin: 14px 0; }
  .mode { display: flex; align-items: center; gap: 10px; padding: 10px 12px; margin-bottom: 14px; border-radius: 8px; background: color-mix(in srgb, var(--mc) 12%, var(--color-surface-1)); border: 1px solid var(--mc); }
  .mode.alarm { animation: pulse 1s ease-in-out infinite; }
  .mode .mdot { width: 12px; height: 12px; border-radius: 50%; background: var(--mc); box-shadow: 0 0 10px var(--mc); }
  .mode .mlabel { font-size: 0.95rem; font-weight: 700; color: var(--mc); letter-spacing: 0.02em; }
  .mode .msub { font-size: 0.62rem; color: var(--color-muted); text-transform: uppercase; letter-spacing: 0.06em; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }
</style>
