<script lang="ts">
  import type { FrameEvent } from "../lib/types";
  let { event }: { event: FrameEvent | undefined } = $props();

  const d = $derived(event?.decision);
  const colour = (p?: string) =>
    p === "GREEN" ? "#2ecc71" : p === "YELLOW" ? "#f1c40f" : "#e74c3c";
</script>

<section class="panel">
  <h2>Decision</h2>
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
  .note { margin-top: 14px; font-size: 0.7rem; color: #6b7688; line-height: 1.4; }
  .empty { color: #667; font-size: 0.85rem; }
</style>
