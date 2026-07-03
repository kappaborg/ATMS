<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { setScene, snapshotFrame, type SceneInfo } from "../lib/gateway";

  let { camera_id, onclose }: { camera_id: string; onclose: () => void } = $props();

  type Pt = { ix: number; iy: number; X: number; Y: number };
  type Zone = { name: string; direction: "ns" | "ew"; verts: [number, number][] };

  let backdrop = $state("");
  let nw = $state(1280);
  let nh = $state(720);
  let loadError = $state("");

  let mode = $state<"points" | "zones">("points");
  let points = $state<Pt[]>([]);
  let zones = $state<Zone[]>([]);
  let draft = $state<[number, number][]>([]);
  let draftName = $state("");
  let draftDir = $state<"ns" | "ew">("ns");

  let applying = $state(false);
  let result = $state<SceneInfo | null>(null);
  let error = $state("");

  onMount(async () => {
    try {
      backdrop = await snapshotFrame(camera_id);
    } catch (e) {
      loadError = (e as Error).message;
    }
  });
  onDestroy(() => backdrop && URL.revokeObjectURL(backdrop));

  function onImgLoad(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    nw = img.naturalWidth || nw;
    nh = img.naturalHeight || nh;
  }

  function stageClick(e: MouseEvent) {
    const rect = (e.currentTarget as SVGElement).getBoundingClientRect();
    const ix = Math.round(((e.clientX - rect.left) / rect.width) * nw);
    const iy = Math.round(((e.clientY - rect.top) / rect.height) * nh);
    if (mode === "points") {
      points = [...points, { ix, iy, X: 0, Y: 0 }];
    } else {
      draft = [...draft, [ix, iy]];
    }
  }

  function removePoint(i: number) {
    points = points.filter((_, k) => k !== i);
  }
  function finishZone() {
    if (draft.length < 3 || !draftName.trim()) {
      error = "a zone needs a name and at least 3 points";
      return;
    }
    error = "";
    zones = [...zones, { name: draftName.trim(), direction: draftDir, verts: draft }];
    draft = [];
    draftName = "";
  }
  function removeZone(i: number) {
    zones = zones.filter((_, k) => k !== i);
  }

  async function apply() {
    error = "";
    result = null;
    if (points.length && points.length < 4) {
      error = "calibration needs at least 4 reference points (or none)";
      return;
    }
    applying = true;
    try {
      const payload: Parameters<typeof setScene>[1] = {};
      if (points.length >= 4) {
        payload.calibration = {
          image_points: points.map((p) => [p.ix, p.iy] as [number, number]),
          world_points_m: points.map((p) => [p.X, p.Y] as [number, number]),
        };
      }
      if (zones.length) {
        payload.zones = Object.fromEntries(zones.map((z) => [z.name, z.verts]));
        payload.zone_directions = Object.fromEntries(zones.map((z) => [z.name, z.direction]));
      }
      result = await setScene(camera_id, payload);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      applying = false;
    }
  }

  const zoneColour = (dir: string) => (dir === "ns" ? "#2ecc71" : "#f1c40f");
</script>

<div class="modal" role="dialog" aria-modal="true">
  <div class="sheet">
    <header>
      <h2>Calibrate — {camera_id}</h2>
      <div class="tabs">
        <button class:active={mode === "points"} onclick={() => (mode = "points")}>Reference points</button>
        <button class:active={mode === "zones"} onclick={() => (mode = "zones")}>Approach zones</button>
      </div>
      <button class="close" onclick={onclose}>✕</button>
    </header>

    <div class="content">
      <div class="stage-wrap">
        {#if loadError}
          <div class="err-box">Could not load a frame: {loadError}</div>
        {:else if !backdrop}
          <div class="err-box">Capturing frame…</div>
        {:else}
          <div class="stage">
            <img src={backdrop} alt="frame" onload={onImgLoad} />
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <svg viewBox="0 0 {nw} {nh}" onclick={stageClick}>
              {#each zones as z}
                <polygon points={z.verts.map((v) => v.join(",")).join(" ")}
                  fill={zoneColour(z.direction)} fill-opacity="0.18" stroke={zoneColour(z.direction)} stroke-width="3" />
                <text x={z.verts[0][0]} y={z.verts[0][1] - 6} fill={zoneColour(z.direction)} font-size={Math.max(14, nh/40)}>{z.name}</text>
              {/each}
              {#if draft.length}
                <polyline points={draft.map((v) => v.join(",")).join(" ")} fill="none" stroke="#7fd1ff" stroke-width="3" stroke-dasharray="8 6" />
                {#each draft as v}
                  <circle cx={v[0]} cy={v[1]} r={Math.max(5, nh/120)} fill="#7fd1ff" />
                {/each}
              {/if}
              {#each points as p, i}
                <circle cx={p.ix} cy={p.iy} r={Math.max(6, nh/100)} fill="#e74c3c" stroke="#fff" stroke-width="2" />
                <text x={p.ix + 10} y={p.iy - 8} fill="#fff" font-size={Math.max(14, nh/40)}>{i + 1}</text>
              {/each}
            </svg>
          </div>
        {/if}
        <p class="hint">
          {#if mode === "points"}
            Click ≥4 points on the road, then enter each point's real-world position in metres (pick a fixed origin, e.g. a lane corner).
          {:else}
            Click to trace an approach zone's outline, name it, pick its direction, then “Finish zone”.
          {/if}
        </p>
      </div>

      <aside>
        {#if mode === "points"}
          <h3>Reference points ({points.length})</h3>
          <p class="sub">image → world metres</p>
          <div class="list">
            {#each points as p, i}
              <div class="row">
                <span class="idx">{i + 1}</span>
                <span class="px">{p.ix},{p.iy}</span>
                <input type="number" step="0.1" bind:value={p.X} title="X metres" />
                <input type="number" step="0.1" bind:value={p.Y} title="Y metres" />
                <button class="x" onclick={() => removePoint(i)}>✕</button>
              </div>
            {/each}
            {#if !points.length}<p class="empty">Click points on the image.</p>{/if}
          </div>
        {:else}
          <h3>Zones ({zones.length})</h3>
          <div class="list">
            {#each zones as z, i}
              <div class="zrow">
                <span class="dot" style="background:{zoneColour(z.direction)}"></span>
                <span class="zname">{z.name}</span>
                <span class="zdir">{z.direction.toUpperCase()}</span>
                <button class="x" onclick={() => removeZone(i)}>✕</button>
              </div>
            {/each}
          </div>
          <div class="zbuild">
            <input placeholder="zone name (e.g. north)" bind:value={draftName} />
            <div class="dirs">
              <button class:active={draftDir === "ns"} onclick={() => (draftDir = "ns")}>N–S</button>
              <button class:active={draftDir === "ew"} onclick={() => (draftDir = "ew")}>E–W</button>
            </div>
            <button class="finish" onclick={finishZone} disabled={draft.length < 3}>Finish zone ({draft.length} pts)</button>
          </div>
        {/if}

        {#if error}<p class="apply-err">{error}</p>{/if}
        {#if result}
          <p class="apply-ok">
            Applied ✓ {result.calibrated ? `— reprojection ${(result.reprojection_error_m! * 100).toFixed(0)} cm` : ""}
            {result.zones.length ? `— ${result.zones.length} zone(s)` : ""}
          </p>
        {/if}
        <button class="apply" onclick={apply} disabled={applying}>{applying ? "applying…" : "Apply to camera"}</button>
      </aside>
    </div>
  </div>
</div>

<style>
  .modal { position: fixed; inset: 0; background: rgba(0,0,0,0.75); display: grid; place-items: center; z-index: 100; }
  .sheet { width: min(1200px, 94vw); height: min(800px, 92vh); background: #0b0d12; border: 1px solid #1e2230; border-radius: 10px; display: flex; flex-direction: column; overflow: hidden; }
  header { display: flex; align-items: center; gap: 16px; padding: 12px 16px; border-bottom: 1px solid #1e2230; }
  header h2 { margin: 0; font-size: 1rem; }
  .tabs { display: flex; gap: 6px; margin-left: 8px; }
  .tabs button, .dirs button { padding: 6px 12px; background: #12151d; border: 1px solid #1e2230; color: #9aa4b2; border-radius: 6px; cursor: pointer; font-size: 0.8rem; }
  .tabs button.active, .dirs button.active { background: #1b3a52; border-color: #2b6ea3; color: #cfe8ff; }
  .close { margin-left: auto; background: none; border: none; color: #9aa4b2; font-size: 1.1rem; cursor: pointer; }
  .content { flex: 1; display: grid; grid-template-columns: 1fr 320px; min-height: 0; }
  .stage-wrap { padding: 14px; display: flex; flex-direction: column; min-height: 0; }
  .stage { position: relative; background: #000; border-radius: 6px; overflow: hidden; }
  .stage img { display: block; width: 100%; height: auto; }
  .stage svg { position: absolute; inset: 0; width: 100%; height: 100%; cursor: crosshair; }
  .hint { font-size: 0.78rem; color: #8b95a7; margin: 10px 2px 0; line-height: 1.4; }
  .err-box { display: grid; place-items: center; aspect-ratio: 16/9; color: #8b95a7; background: #000; border-radius: 6px; }
  aside { border-left: 1px solid #1e2230; padding: 14px; display: flex; flex-direction: column; overflow: auto; }
  aside h3 { margin: 0 0 2px; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; color: #8b95a7; }
  .sub { margin: 0 0 8px; font-size: 0.7rem; color: #6b7688; }
  .list { display: flex; flex-direction: column; gap: 6px; }
  .row { display: grid; grid-template-columns: 20px 60px 1fr 1fr 22px; gap: 6px; align-items: center; }
  .row .idx { color: #e74c3c; font-weight: 600; font-size: 0.8rem; }
  .row .px { font-size: 0.72rem; color: #6b7688; }
  .row input { width: 100%; padding: 4px 6px; background: #12151d; border: 1px solid #1e2230; border-radius: 4px; color: #eaf1f8; font-size: 0.78rem; }
  .zrow { display: grid; grid-template-columns: 12px 1fr auto 22px; gap: 8px; align-items: center; font-size: 0.82rem; }
  .zrow .dot { width: 10px; height: 10px; border-radius: 50%; }
  .zrow .zdir { font-size: 0.7rem; color: #8b95a7; }
  .x { background: none; border: none; color: #7a8494; cursor: pointer; }
  .zbuild { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
  .zbuild input { padding: 7px 9px; background: #12151d; border: 1px solid #1e2230; border-radius: 5px; color: #eaf1f8; font-size: 0.82rem; }
  .dirs { display: flex; gap: 6px; }
  .dirs button { flex: 1; }
  .finish { padding: 7px; background: #24425c; border: 1px solid #2b6ea3; color: #cfe8ff; border-radius: 5px; cursor: pointer; }
  .finish:disabled { opacity: 0.5; cursor: default; }
  .empty { color: #667; font-size: 0.8rem; }
  .apply { margin-top: auto; padding: 10px; background: #2b6ea3; border: none; border-radius: 6px; color: #fff; font-weight: 600; cursor: pointer; }
  .apply:disabled { opacity: 0.6; }
  .apply-err { color: #e74c3c; font-size: 0.76rem; }
  .apply-ok { color: #2ecc71; font-size: 0.76rem; }
</style>
