<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { getViolations, violationSnapshotUrl, exportViolations, type ViolationRecord } from "../lib/gateway";
  import Icon, { type IconName } from "./Icon.svelte";

  // CSV export is operator-only server-side (bulk PII); hide it from viewers.
  let { canOperate = false }: { canOperate?: boolean } = $props();

  let rows = $state<ViolationRecord[]>([]);
  let filterType = $state("");
  let hours = $state(24);
  let zoom = $state<number | null>(null); // id of snapshot to enlarge

  const TYPES = ["speeding", "red_light", "wrong_way", "reckless", "drift", "stopped_vehicle"];
  const label: Record<string, string> = {
    speeding: "Speeding", red_light: "Ran red", wrong_way: "Wrong-way",
    reckless: "Reckless", drift: "Drift", stopped_vehicle: "Stopped",
  };
  const icon: Record<string, IconName> = {
    speeding: "speed", red_light: "signal", wrong_way: "no-entry",
    reckless: "reckless", drift: "drift", stopped_vehicle: "warning",
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
    // Initial fetch is owned by the $effect below (it runs once on mount too),
    // so onMount only needs to set up the periodic refresh.
    timer = setInterval(load, 5000);
  });
  onDestroy(() => clearInterval(timer));
  $effect(() => {
    filterType;
    hours;
    load();
  });
</script>

<svelte:window onkeydown={(e) => { if (e.key === "Escape" && zoom !== null) zoom = null; }} />

<div class="wrap">
  <div class="bar">
    <div class="bar-top">
      <h2>Alerts</h2>
      <span class="sub">evidence log · kept 30 days, then deleted</span>
      <span class="spacer"></span>
      <select bind:value={hours}>
        <option value={1}>last hour</option>
        <option value={24}>last 24h</option>
        <option value={168}>last 7 days</option>
        <option value={720}>last 30 days</option>
      </select>
      {#if canOperate}<button class="export" onclick={exportViolations}><Icon name="download" size={14} />Export CSV</button>{/if}
    </div>
    <div class="chips">
      <button class="chip" class:on={filterType === ""} onclick={() => (filterType = "")}>Everything</button>
      {#each TYPES as t}
        <button class="chip" class:on={filterType === t} onclick={() => (filterType = t)}><Icon name={icon[t]} size={14} />{label[t]}</button>
      {/each}
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
            <td><span class="type {r.type}">{#if icon[r.type]}<Icon name={icon[r.type]} size={13} />{/if}{label[r.type] ?? r.type}</span></td>
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
  .bar { display: flex; flex-direction: column; gap: 12px; padding: 16px; border-bottom: 1px solid var(--color-border); }
  .bar-top { display: flex; align-items: baseline; gap: 10px; }
  h2 { font-size: 1.15rem; font-weight: 700; letter-spacing: -0.01em; color: var(--color-text); margin: 0; }
  .sub { font-size: 0.78rem; color: var(--color-muted); }
  .bar-top .spacer { flex: 1; }
  .bar-top select, .export { background: var(--color-surface-1); border: 1px solid var(--color-border-2); color: var(--color-text); border-radius: 100px; padding: 6px 13px; font-size: 0.8rem; cursor: pointer; box-shadow: var(--sh-1); }
  .export { display: inline-flex; align-items: center; gap: 6px; }
  .bar-top select:hover, .export:hover { background: var(--color-surface-2); }
  .chips { display: flex; gap: 7px; flex-wrap: wrap; }
  .chip { display: inline-flex; align-items: center; gap: 6px; font-size: 0.8rem; font-weight: 550; color: var(--color-muted); background: var(--color-surface-1); border: 1px solid var(--color-border-2); padding: 6px 13px; border-radius: 100px; cursor: pointer; box-shadow: var(--sh-1); }
  .chip:hover { background: var(--color-surface-2); color: var(--color-text); }
  .chip.on { color: #fff; border-color: var(--color-accent); background: var(--color-accent); }
  .tablewrap { overflow: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  th { position: sticky; top: 0; background: var(--color-surface-1); color: var(--color-muted); text-align: left; padding: 8px 12px; font-weight: 500; border-bottom: 1px solid var(--color-border); }
  td { padding: 6px 12px; border-bottom: 1px solid var(--color-border); color: var(--color-text); }
  .thumb { padding: 0; border: 1px solid var(--color-border-2); background: none; cursor: pointer; border-radius: 4px; overflow: hidden; }
  .thumb img { width: 64px; height: 40px; object-fit: cover; display: block; }
  .nosnap { color: var(--color-dim); }
  .t { color: var(--color-muted); white-space: nowrap; }
  .plate { font-family: ui-monospace, monospace; color: var(--color-text); letter-spacing: 0.03em; }
  .det { color: var(--color-muted); }
  .type { display: inline-flex; align-items: center; gap: 5px; font-size: 0.72rem; padding: 2px 7px; border-radius: 4px; background: var(--color-surface-2); }
  .type.speeding { color: var(--color-warn); } .type.red_light { color: var(--color-critical); }
  .type.wrong_way { color: var(--color-critical); } .type.drift { color: var(--color-accent-dim); }
  .type.reckless { color: #8a6fbf; } .type.stopped_vehicle { color: var(--color-critical); }
  .empty { text-align: center; color: var(--color-dim); padding: 30px; }
  .lightbox { position: fixed; inset: 0; background: rgba(0,0,0,0.85); display: grid; place-items: center; z-index: 100; cursor: zoom-out; }
  .lightbox img { max-width: 80vw; max-height: 80vh; border: 1px solid var(--color-border-2); border-radius: 6px; }
</style>
