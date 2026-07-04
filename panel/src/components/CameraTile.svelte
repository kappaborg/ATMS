<script lang="ts">
  import { onDestroy } from "svelte";
  import { connectVideo, removeCamera } from "../lib/gateway";
  import type { FrameEvent } from "../lib/types";

  let {
    camera_id,
    event,
    live = true,
    kind = "file",
  }: { camera_id: string; event: FrameEvent | undefined; live?: boolean; kind?: string } = $props();

  let src = $state<string>("");
  // camera_id is fixed per tile instance (the grid keys tiles by id).
  // svelte-ignore state_referenced_locally
  const stop = connectVideo(camera_id, (url) => (src = url));
  onDestroy(stop);

  const phaseColour = (p?: string) =>
    p === "GREEN" ? "#2ecc71" : p === "YELLOW" ? "#f1c40f" : p === "ALL_RED" || p === "RED" ? "#e74c3c" : "#888";

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
    // keep the point under the cursor fixed while zooming
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
    <div class="srcbadge" class:live>{live ? "● LIVE" : "FILE"} · {kind.toUpperCase()}</div>
    {#if scale > 1}
      <button class="zoomreset" onclick={reset} title="Reset zoom">{scale.toFixed(1)}× ✕</button>
    {/if}
    <div class="badge">
      <span class="dot" style="background:{phaseColour(event?.decision.phase)}"></span>
      {camera_id}
      {#if event}
        <span class="stat">🚗 {event.counts.vehicles}</span>
        <span class="stat">🚶 {event.counts.pedestrians}</span>
        <span class="stat">{event.fps.toFixed(0)} fps</span>
        <span class="stat lat">{event.pipeline_latency_ms.toFixed(0)} ms</span>
      {/if}
    </div>
    {#if event?.violations?.length}
      <div class="violations">
        {#each event.violations.slice(0, 3) as v}
          <div class="vio {v.type}">
            {#if v.type === "drift"}💨 DRIFT <span>#{v.track_id} · {v.lateral_g}g{v.plate ? " · " + v.plate : ""}</span>
            {:else if v.type === "wrong_way"}⛔ WRONG-WAY <span>#{v.track_id}{v.plate ? " · " + v.plate : ""}</span>
            {:else if v.type === "red_light"}🚦 RAN RED <span>#{v.track_id} · {v.approach?.toUpperCase()}{v.plate ? " · " + v.plate : ""}</span>
            {:else if v.type === "reckless"}🌀 RECKLESS <span>#{v.track_id}{v.plate ? " · " + v.plate : ""}</span>
            {:else if v.type === "speeding"}⚡ SPEEDING <span>#{v.track_id} · {v.speed_kmh?.toFixed(0)}/{v.limit_kmh} km/h{v.plate ? " · " + v.plate : ""}</span>
            {:else}⚠ STOPPED <span>#{v.track_id} · {v.seconds?.toFixed(0)}s</span>{/if}
          </div>
        {/each}
      </div>
    {/if}
    <button class="remove" title="Remove camera" onclick={() => removeCamera(camera_id)}>✕</button>
  </div>
</div>

<style>
  .tile { background: #0d0f14; border: 1px solid #1e2230; border-radius: 8px; overflow: hidden; }
  .video { position: relative; aspect-ratio: 16 / 9; background: #000; overflow: hidden; }
  img { width: 100%; height: 100%; object-fit: contain; display: block; will-change: transform; }
  .srcbadge {
    position: absolute; top: 8px; left: 8px; font-size: 0.62rem; font-weight: 600;
    letter-spacing: 0.04em; padding: 3px 7px; border-radius: 4px;
    background: rgba(0,0,0,0.6); color: #9aa4b2;
  }
  .srcbadge.live { color: #2ecc71; }
  .zoomreset {
    position: absolute; top: 8px; left: 50%; transform: translateX(-50%);
    background: rgba(0,0,0,0.65); color: #cfe8ff; border: 1px solid #2b6ea3;
    border-radius: 4px; padding: 3px 8px; font-size: 0.68rem; cursor: pointer;
  }
  .placeholder { position: absolute; inset: 0; display: grid; place-items: center; color: #667; font-size: 0.85rem; }
  .violations { position: absolute; top: 8px; left: 8px; display: flex; flex-direction: column; gap: 4px; }
  .vio {
    display: flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 6px;
    font-size: 0.72rem; font-weight: 700; color: #fff;
    animation: incpulse 1.2s ease-in-out infinite;
  }
  .vio span { font-weight: 400; opacity: 0.85; }
  .vio.stopped_vehicle { background: rgba(231,76,60,0.92); box-shadow: 0 0 12px rgba(231,76,60,0.6); }
  .vio.wrong_way { background: rgba(200,0,200,0.92); box-shadow: 0 0 12px rgba(200,0,200,0.6); }
  .vio.red_light { background: rgba(180,20,20,0.95); box-shadow: 0 0 12px rgba(180,20,20,0.7); }
  .vio.reckless { background: rgba(155,30,120,0.92); box-shadow: 0 0 12px rgba(155,30,120,0.6); }
  .vio.drift { background: rgba(0,180,190,0.92); box-shadow: 0 0 12px rgba(0,180,190,0.6); }
  .vio.speeding { background: rgba(230,126,34,0.92); box-shadow: 0 0 12px rgba(230,126,34,0.5); }
  @keyframes incpulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
  .badge {
    position: absolute; left: 8px; bottom: 8px; display: flex; align-items: center; gap: 8px;
    background: rgba(0,0,0,0.55); padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; color: #dfe6ee;
  }
  .dot { width: 10px; height: 10px; border-radius: 50%; box-shadow: 0 0 6px currentColor; }
  .stat { opacity: 0.9; }
  .stat.lat { color: #7fd1ff; }
  .remove {
    position: absolute; top: 8px; right: 8px; background: rgba(0,0,0,0.5); color: #fff; border: none;
    border-radius: 4px; width: 24px; height: 24px; cursor: pointer; opacity: 0; transition: opacity .15s;
  }
  .tile:hover .remove { opacity: 1; }
</style>
