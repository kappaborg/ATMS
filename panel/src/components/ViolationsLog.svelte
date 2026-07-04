<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { getViolations, violationSnapshotUrl, exportViolations, type ViolationRecord } from "../lib/gateway";

  let rows = $state<ViolationRecord[]>([]);
  let filterType = $state("");
  let hours = $state(24);
  let zoom = $state<number | null>(null); // id of snapshot to enlarge

  const TYPES = ["speeding", "red_light", "wrong_way", "reckless", "drift", "stopped_vehicle"];
  const label: Record<string, string> = {
    speeding: "⚡ Speeding", red_light: "🚦 Ran red", wrong_way: "⛔ Wrong-way",
    reckless: "🌀 Reckless", drift: "💨 Drift", stopped_vehicle: "⚠ Stopped",
  };

  async function load() {
    rows = await getViolations(hours, undefined, filterType || undefined);
  }
  const fmt = (ts: number) => new Date(ts * 1000).toLocaleString();
  function detailStr(r: ViolationRecord) {
    const d = r.detail || {};
    if (r.type === "speeding") return `${d.speed_kmh}/${d.limit_kmh} km/h`;
    if (r.type === "drift") return `${d.lateral_g} g`;
    if (r.type === "red_light") return String(d.approach ?? "").toUpperCase();
    if (r.type === "stopped_vehicle") return `${d.seconds}s`;
    if (r.type === "reckless") return `${d.reversals ?? ""} rev`;
    return "";
  }

  let timer: ReturnType<typeof setInterval>;
  onMount(() => {
    load();
    timer = setInterval(load, 5000);
  });
  onDestroy(() => clearInterval(timer));
  $effect(() => {
    filterType;
    hours;
    load();
  });
</script>

<div class="wrap">
  <div class="bar">
    <h2>Violation evidence log</h2>
    <div class="controls">
      <select bind:value={filterType}>
        <option value="">all types</option>
        {#each TYPES as t}<option value={t}>{label[t]}</option>{/each}
      </select>
      <select bind:value={hours}>
        <option value={1}>last hour</option>
        <option value={24}>last 24h</option>
        <option value={168}>last 7 days</option>
        <option value={720}>last 30 days</option>
      </select>
      <button onclick={exportViolations}>⤓ Export CSV</button>
    </div>
  </div>

  <div class="tablewrap">
    <table>
      <thead>
        <tr><th>Snapshot</th><th>Time</th><th>Type</th><th>Plate</th><th>Detail</th><th>Camera</th><th>Int</th></tr>
      </thead>
      <tbody>
        {#each rows as r (r.id)}
          <tr>
            <td>
              {#if r.has_snapshot}
                <button class="thumb" onclick={() => (zoom = r.id)} aria-label="enlarge">
                  <img src={violationSnapshotUrl(r.id)} alt="evidence" loading="lazy" />
                </button>
              {:else}<span class="nosnap">—</span>{/if}
            </td>
            <td class="t">{fmt(r.ts)}</td>
            <td><span class="type {r.type}">{label[r.type] ?? r.type}</span></td>
            <td class="plate">{r.plate ?? "—"}</td>
            <td class="det">{detailStr(r)}</td>
            <td>{r.camera_id}</td>
            <td>{r.intersection_id}</td>
          </tr>
        {:else}
          <tr><td colspan="7" class="empty">No violations logged in this window.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if zoom !== null}
    <div class="lightbox" role="button" tabindex="0" aria-label="close preview"
      onclick={() => (zoom = null)}
      onkeydown={(e) => (e.key === "Escape" || e.key === "Enter") && (zoom = null)}>
      <img src={violationSnapshotUrl(zoom)} alt="evidence enlarged" />
    </div>
  {/if}
</div>

<style>
  .wrap { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
  .bar { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; border-bottom: 1px solid #1e2230; }
  h2 { font-size: 0.95rem; color: #cfe8ff; margin: 0; }
  .controls { display: flex; gap: 8px; }
  .controls select, .controls button { background: #11151d; border: 1px solid #232838; color: #cfe8ff; border-radius: 6px; padding: 5px 10px; font-size: 0.78rem; cursor: pointer; }
  .tablewrap { overflow: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  th { position: sticky; top: 0; background: #0d0f14; color: #8b95a7; text-align: left; padding: 8px 12px; font-weight: 500; border-bottom: 1px solid #1e2230; }
  td { padding: 6px 12px; border-bottom: 1px solid #14171f; color: #dfe6ee; }
  .thumb { padding: 0; border: 1px solid #2b3547; background: none; cursor: pointer; border-radius: 4px; overflow: hidden; }
  .thumb img { width: 64px; height: 40px; object-fit: cover; display: block; }
  .nosnap { color: #556; }
  .t { color: #9aa4b2; white-space: nowrap; }
  .plate { font-family: ui-monospace, monospace; color: #eaf1f8; letter-spacing: 0.03em; }
  .det { color: #9aa4b2; }
  .type { font-size: 0.72rem; padding: 2px 7px; border-radius: 4px; background: #1a2331; }
  .type.speeding { color: #f0a04b; } .type.red_light { color: #ff7a7a; }
  .type.wrong_way { color: #e07ce0; } .type.drift { color: #4fd0da; }
  .type.reckless { color: #d18ad1; } .type.stopped_vehicle { color: #e6a4a4; }
  .empty { text-align: center; color: #667; padding: 30px; }
  .lightbox { position: fixed; inset: 0; background: rgba(0,0,0,0.85); display: grid; place-items: center; z-index: 100; cursor: zoom-out; }
  .lightbox img { max-width: 80vw; max-height: 80vh; border: 1px solid #2b3547; border-radius: 6px; }
</style>
