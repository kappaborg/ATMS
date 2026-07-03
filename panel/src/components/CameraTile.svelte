<script lang="ts">
  import { onDestroy } from "svelte";
  import { connectVideo, removeCamera } from "../lib/gateway";
  import type { FrameEvent } from "../lib/types";

  let { camera_id, event }: { camera_id: string; event: FrameEvent | undefined } = $props();

  let src = $state<string>("");
  const stop = connectVideo(camera_id, (url) => (src = url));
  onDestroy(stop);

  const phaseColour = (p?: string) =>
    p === "GREEN" ? "#2ecc71" : p === "YELLOW" ? "#f1c40f" : p === "ALL_RED" || p === "RED" ? "#e74c3c" : "#888";
</script>

<div class="tile">
  <div class="video">
    {#if src}
      <img {src} alt={camera_id} />
    {:else}
      <div class="placeholder">connecting {camera_id}…</div>
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
    {#if event?.incidents?.length}
      <div class="incident">⚠ {event.incidents.length === 1 ? "Stopped vehicle" : `${event.incidents.length} stopped vehicles`}
        <span>#{event.incidents[0].track_id} · {event.incidents[0].seconds.toFixed(0)}s</span>
      </div>
    {/if}
    <button class="remove" title="Remove camera" onclick={() => removeCamera(camera_id)}>✕</button>
  </div>
</div>

<style>
  .tile { background: #0d0f14; border: 1px solid #1e2230; border-radius: 8px; overflow: hidden; }
  .video { position: relative; aspect-ratio: 16 / 9; background: #000; }
  img { width: 100%; height: 100%; object-fit: contain; display: block; }
  .placeholder { position: absolute; inset: 0; display: grid; place-items: center; color: #667; font-size: 0.85rem; }
  .incident {
    position: absolute; top: 8px; left: 8px; display: flex; align-items: center; gap: 6px;
    background: rgba(231,76,60,0.92); color: #fff; padding: 4px 10px; border-radius: 6px;
    font-size: 0.74rem; font-weight: 600; box-shadow: 0 0 12px rgba(231,76,60,0.6);
    animation: incpulse 1.2s ease-in-out infinite;
  }
  .incident span { font-weight: 400; opacity: 0.85; }
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
