<script lang="ts">
  import { onDestroy } from "svelte";
  import { connectVideo, removeCamera } from "../lib/gateway";
  import type { FrameEvent } from "../lib/types";
  import Icon from "./Icon.svelte";

  let {
    camera_id,
    event,
    live = true,
    kind = "file",
    canOperate = false,
  }: { camera_id: string; event: FrameEvent | undefined; live?: boolean; kind?: string; canOperate?: boolean } = $props();

  let src = $state<string>("");
  // camera_id is fixed per tile instance (the grid keys tiles by id).
  // svelte-ignore state_referenced_locally
  const stop = connectVideo(camera_id, (url) => (src = url));
  onDestroy(stop);

  const phaseVar = (p?: string) =>
    p === "GREEN" ? "var(--color-sig-green)" : p === "YELLOW" ? "var(--color-sig-amber)" : "var(--color-sig-red)";
  const phaseClass = (p?: string) => (p === "GREEN" ? "p-green" : p === "YELLOW" ? "p-amber" : "p-red");

  // Digital zoom + pan on the video (inspect a plate / an incident).
  let vbox = $state<HTMLDivElement>();
  let scale = $state(1);
  let panX = $state(0);
  let panY = $state(0);
  let dragging = $state(false);
  let dragStart = { x: 0, y: 0, panX: 0, panY: 0 };
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

  function onwheel(e: WheelEvent) {
    if (!vbox) return;
    e.preventDefault();
    const r = vbox.getBoundingClientRect();
    const cx = e.clientX - r.left;
    const cy = e.clientY - r.top;
    const prev = scale;
    const next = clamp(scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 1, 6);
    panX = cx - ((cx - panX) * next) / prev;
    panY = cy - ((cy - panY) * next) / prev;
    scale = next;
    if (scale <= 1.001) reset();
  }
  function onmousedown(e: MouseEvent) {
    if (scale <= 1) return;
    dragging = true;
    dragStart = { x: e.clientX, y: e.clientY, panX, panY };
  }
  function onmousemove(e: MouseEvent) {
    if (!dragging) return;
    panX = dragStart.panX + (e.clientX - dragStart.x);
    panY = dragStart.panY + (e.clientY - dragStart.y);
  }
  function reset() {
    scale = 1;
    panX = 0;
    panY = 0;
  }
</script>

<svelte:window onmouseup={() => (dragging = false)} onmousemove={onmousemove} />

<div class="tile">
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="video" bind:this={vbox} {onwheel} {onmousedown} ondblclick={reset}
       class:dragging={scale > 1} style="cursor:{scale > 1 ? (dragging ? 'grabbing' : 'grab') : 'default'}">
    {#if src}
      <img {src} alt={camera_id} style="transform: translate({panX}px, {panY}px) scale({scale}); transform-origin: 0 0;" />
    {:else}
      <div class="placeholder">connecting {camera_id}…</div>
    {/if}

    <!-- top overlays -->
    <div class="ov-top">
      <span class="badge" class:live>{#if live}<span class="dot"></span>{/if}{live ? "LIVE" : "FILE"} · {kind.toUpperCase()}</span>
      <span class="spacer"></span>
      {#if event}
        <span class="phase-chip {phaseClass(event.decision.phase)}"><span class="d"></span> {event.decision.phase}</span>
      {/if}
      {#if canOperate}
        <button class="remove" title="Remove camera" onclick={() => removeCamera(camera_id)}><Icon name="close" size={13} stroke={2.2} /></button>
      {/if}
    </div>

    {#if scale > 1}
      <button class="zoomreset" onclick={reset} title="Reset zoom">{scale.toFixed(1)}× <Icon name="close" size={11} stroke={2.2} /></button>
    {/if}

    {#if event?.violations?.length}
      <div class="violations">
        {#each event.violations.slice(0, 3) as v}
          <div class="vio {v.type}">
            {#if v.type === "drift"}<Icon name="drift" size={13} stroke={2} />DRIFT <span>#{v.track_id} · {v.lateral_g}g{v.plate ? " · " + v.plate : ""}</span>
            {:else if v.type === "wrong_way"}<Icon name="no-entry" size={13} stroke={2} />WRONG-WAY <span>#{v.track_id}{v.plate ? " · " + v.plate : ""}</span>
            {:else if v.type === "red_light"}<Icon name="signal" size={13} stroke={2} />RAN RED <span>#{v.track_id} · {v.approach?.toUpperCase()}{v.plate ? " · " + v.plate : ""}</span>
            {:else if v.type === "reckless"}<Icon name="reckless" size={13} stroke={2} />RECKLESS <span>#{v.track_id}{v.plate ? " · " + v.plate : ""}</span>
            {:else if v.type === "speeding"}<Icon name="speed" size={13} stroke={2} />SPEEDING <span>#{v.track_id} · {v.speed_kmh?.toFixed(0)}/{v.limit_kmh} km/h{v.plate ? " · " + v.plate : ""}</span>{/if}
          </div>
        {/each}
      </div>
    {/if}

    <!-- bottom metric strip -->
    <div class="ov-bot">
      <span class="camid">{camera_id}</span>
      {#if event}
        <span class="spacer"></span>
        <div class="m"><b>{event.counts.vehicles}</b><i>veh</i></div>
        <div class="m"><b>{event.counts.pedestrians}</b><i>ped</i></div>
        <div class="m"><b>{event.fps.toFixed(0)}</b><i>fps</i></div>
        <div class="m lat"><b>{event.pipeline_latency_ms.toFixed(0)}</b><i>ms</i></div>
      {/if}
    </div>
  </div>
</div>

<style>
  .tile { background: var(--color-surface-1); border: 1px solid var(--color-border); border-radius: var(--radius-lg); overflow: hidden; }
  .video { position: relative; aspect-ratio: 16 / 9; background: #000; overflow: hidden; }
  img { width: 100%; height: 100%; object-fit: contain; display: block; will-change: transform; }
  .placeholder { position: absolute; inset: 0; display: grid; place-items: center; color: var(--color-dim); font-size: 0.85rem; }

  /* top overlay row */
  .ov-top { position: absolute; top: 8px; left: 8px; right: 8px; display: flex; align-items: center; gap: 7px; }
  .ov-top .spacer { flex: 1; }
  .badge {
    display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 9px; border-radius: 100px;
    font-size: 0.66rem; font-weight: 700; letter-spacing: 0.03em;
    background: rgba(12, 14, 20, 0.72); backdrop-filter: blur(6px); color: #cdd6e2; border: 1px solid rgba(255,255,255,0.08);
  }
  .badge.live { color: #6be2a8; }
  .badge .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; box-shadow: 0 0 6px currentColor; }
  .phase-chip {
    display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 9px; border-radius: 100px;
    font-size: 0.66rem; font-weight: 700; background: rgba(12, 14, 20, 0.72); backdrop-filter: blur(6px);
  }
  .phase-chip .d { width: 8px; height: 8px; border-radius: 50%; }
  .p-green { color: #5fe0a0; } .p-green .d { background: var(--color-sig-green); box-shadow: 0 0 8px var(--color-sig-green); }
  .p-amber { color: #f2c46a; } .p-amber .d { background: var(--color-sig-amber); box-shadow: 0 0 8px var(--color-sig-amber); }
  .p-red { color: #f28a94; } .p-red .d { background: var(--color-sig-red); box-shadow: 0 0 8px var(--color-sig-red); }
  .remove {
    width: 22px; height: 22px; flex: none; display: grid; place-items: center; border-radius: 6px;
    background: rgba(12, 14, 20, 0.6); color: #fff; border: none; cursor: pointer; opacity: 0; transition: opacity 0.15s; font-size: 0.7rem;
  }
  .tile:hover .remove { opacity: 1; }

  .zoomreset {
    position: absolute; top: 38px; left: 50%; transform: translateX(-50%);
    display: inline-flex; align-items: center; gap: 4px;
    background: rgba(12, 14, 20, 0.7); color: #eef2f7; border: 1px solid rgba(255,255,255,0.18);
    border-radius: 6px; padding: 3px 8px; font-size: 0.68rem; cursor: pointer;
  }

  /* live violation banners — high-visibility on video, but no neon glow */
  .violations { position: absolute; top: 40px; left: 8px; display: flex; flex-direction: column; gap: 4px; }
  .vio {
    display: flex; align-items: center; gap: 6px; padding: 4px 9px; border-radius: 6px;
    font-size: 0.72rem; font-weight: 700; color: #fff; animation: incpulse 1.4s ease-in-out infinite;
  }
  .vio :global(svg) { flex: none; }
  .vio span { font-weight: 400; opacity: 0.85; }
  .vio.wrong_way { background: #a23596; }
  .vio.red_light { background: #b32020; }
  .vio.reckless { background: #8e2c6e; }
  .vio.drift { background: #157f86; }
  .vio.speeding { background: #b5732a; }
  @keyframes incpulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.78; } }

  /* bottom metric strip */
  .ov-bot {
    position: absolute; left: 0; right: 0; bottom: 0; display: flex; align-items: flex-end; gap: 13px;
    padding: 20px 12px 9px; background: linear-gradient(0deg, rgba(8, 10, 14, 0.86), transparent);
  }
  .ov-bot .spacer { flex: 1; }
  .camid { font-size: 0.74rem; font-weight: 600; color: #eef2f7; }
  .ov-bot .m { display: flex; flex-direction: column; gap: 1px; align-items: flex-start; }
  .ov-bot .m b { font-size: 0.86rem; font-weight: 700; color: #fff; font-variant-numeric: tabular-nums; }
  .ov-bot .m i { font-style: normal; font-size: 0.58rem; letter-spacing: 0.06em; text-transform: uppercase; color: rgba(255, 255, 255, 0.6); }
  .ov-bot .m.lat b { color: #8fd8ff; }
</style>
