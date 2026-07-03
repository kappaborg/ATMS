<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { setScene, snapshotFrame, type SceneInfo } from "../lib/gateway";

  let { camera_id, onclose }: { camera_id: string; onclose: () => void } = $props();

  // Points are stored in NORMALISED coordinates (nx, ny in 0..1 relative to
  // the image), so clicks land exactly under the cursor regardless of the
  // video's resolution, aspect ratio, or rotation. Pixels are computed once,
  // at apply time, from the image's natural dimensions.
  type Pt = { nx: number; ny: number; X: number; Y: number };
  type Zone = { name: string; direction: "ns" | "ew"; verts: [number, number][] };

  let backdrop = $state("");
  let loadError = $state("");
  let imgEl: HTMLImageElement | undefined = $state();
  let stageW = $state(1);
  let stageH = $state(1);

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

  function stageClick(e: MouseEvent) {
    // Map the click to 0..1 within the image element itself.
    const el = e.currentTarget as HTMLElement;
    const rect = el.getBoundingClientRect();
    const nx = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const ny = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    if (mode === "points") {
      points = [...points, { nx, ny, X: 0, Y: 0 }];
    } else {
      draft = [...draft, [nx, ny]];
    }
  }

  // Normalised -> rendered pixels for drawing the overlay.
  const px = (n: number, span: number) => n * span;
  // Normalised -> image pixels for the gateway (uses real frame size).
  function toImagePx(nx: number, ny: number): [number, number] {
    const w = imgEl?.naturalWidth || 1;
    const h = imgEl?.naturalHeight || 1;
    return [Math.round(nx * w), Math.round(ny * h)];
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
          image_points: points.map((p) => toImagePx(p.nx, p.ny)),
          world_points_m: points.map((p) => [p.X, p.Y] as [number, number]),
        };
      }
      if (zones.length) {
        payload.zones = Object.fromEntries(
          zones.map((z) => [z.name, z.verts.map(([nx, ny]) => toImagePx(nx, ny))]),
        );
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
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <div class="stage" bind:clientWidth={stageW} bind:clientHeight={stageH} onclick={stageClick}>
            <img src={backdrop} alt="frame" bind:this={imgEl} />
            <svg viewBox="0 0 {stageW} {stageH}">
              {#each zones as z}
                <polygon points={z.verts.map(([nx, ny]) => `${px(nx, stageW)},${px(ny, stageH)}`).join(" ")}
                  fill={zoneColour(z.direction)} fill-opacity="0.18" stroke={zoneColour(z.direction)} stroke-width="2.5" />
                <text x={px(z.verts[0][0], stageW)} y={px(z.verts[0][1], stageH) - 6} fill={zoneColour(z.direction)} font-size="15">{z.name}</text>
              {/each}
              {#if draft.length}
                <polyline points={draft.map(([nx, ny]) => `${px(nx, stageW)},${px(ny, stageH)}`).join(" ")} fill="none" stroke="#7fd1ff" stroke-width="2.5" stroke-dasharray="8 6" />
                {#each draft as [nx, ny]}
                  <circle cx={px(nx, stageW)} cy={px(ny, stageH)} r="5" fill="#7fd1ff" />
                {/each}
              {/if}
              {#each points as p, i}
                <circle cx={px(p.nx, stageW)} cy={px(p.ny, stageH)} r="7" fill="#e74c3c" stroke="#fff" stroke-width="2" />
                <text x={px(p.nx, stageW) + 11} y={px(p.ny, stageH) - 9} fill="#fff" font-size="15">{i + 1}</text>
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
                <span class="px">{(p.nx * 100).toFixed(0)},{(p.ny * 100).toFixed(0)}%</span>
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
  .stage-wrap { padding: 14px; display: flex; flex-direction: column; align-items: center; min-height: 0; }
  /* The stage shrinks to the rendered image (any aspect/orientation), so the
     click overlay and the image share exactly the same box — clicks always
     land under the cursor. */
  .stage { position: relative; display: inline-block; line-height: 0; background: #000; border-radius: 6px; overflow: hidden; cursor: crosshair; }
  .stage img { display: block; width: auto; height: auto; max-width: 100%; max-height: 64vh; }
  .stage svg { position: absolute; inset: 0; width: 100%; height: 100%; }
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
