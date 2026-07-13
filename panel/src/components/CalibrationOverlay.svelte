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

  let mode = $state<"points" | "zones" | "stoplines">("points");
  // "rect" = click 4 corners of a ground rectangle + enter its size (easy).
  // "advanced" = enter each point's own X/Y metres.
  let calMode = $state<"rect" | "advanced">("rect");
  let rectW = $state(0); // rectangle width across the road (metres)
  let rectL = $state(0); // rectangle length along the road (metres)
  let points = $state<Pt[]>([]);
  let zones = $state<Zone[]>([]);
  let draft = $state<[number, number][]>([]);
  let draftName = $state("");
  let draftDir = $state<"ns" | "ew">("ns");
  // Stop-lines for red-light-running: each is 2 points + an approach.
  let stopLines = $state<{ approach: "ns" | "ew"; verts: [number, number][] }[]>([]);
  let slDraft = $state<[number, number][]>([]);
  let slDir = $state<"ns" | "ew">("ns");

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
      // In rectangle mode, cap at 4 corners.
      if (calMode === "rect" && points.length >= 4) return;
      points = [...points, { nx, ny, X: 0, Y: 0 }];
    } else if (mode === "zones") {
      draft = [...draft, [nx, ny]];
    } else {
      // Stop-line: two clicks make one line.
      const next = [...slDraft, [nx, ny] as [number, number]];
      if (next.length === 2) {
        stopLines = [...stopLines, { approach: slDir, verts: next }];
        slDraft = [];
      } else {
        slDraft = next;
      }
    }
  }

  function removeStopLine(i: number) {
    stopLines = stopLines.filter((_, k) => k !== i);
  }

  function clearPoints() {
    points = [];
    error = "";
    result = null;
  }

  // Reject clustered/collinear image points before hitting the backend.
  function pointsAreSpread(): boolean {
    if (points.length < 4) return false;
    const xs = points.map((p) => p.nx);
    const ys = points.map((p) => p.ny);
    return Math.max(...xs) - Math.min(...xs) > 0.06 && Math.max(...ys) - Math.min(...ys) > 0.06;
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

  function buildCalibration(): { image_points: [number, number][]; world_points_m: [number, number][] } | null {
    if (points.length === 0) return null; // calibration optional (zones only)
    if (points.length < 4) {
      throw new Error("click at least 4 points on the road");
    }
    if (!pointsAreSpread()) {
      throw new Error("spread the points out across the road — they're clustered too close together");
    }
    const image_points = points.map((p) => toImagePx(p.nx, p.ny));

    if (calMode === "rect") {
      if (points.length !== 4) throw new Error("rectangle mode needs exactly 4 corners");
      if (!(rectW > 0) || !(rectL > 0)) {
        throw new Error("enter the rectangle's width and length in metres");
      }
      // Corners in click order: near-left, near-right, far-right, far-left.
      return {
        image_points,
        world_points_m: [[0, 0], [rectW, 0], [rectW, rectL], [0, rectL]],
      };
    }

    // Advanced: each point needs its own real-world metres, and they must
    // not all be the same point.
    const distinct = new Set(points.map((p) => `${p.X},${p.Y}`)).size;
    if (distinct < 3) {
      throw new Error("enter distinct real-world metres for the points (not all 0)");
    }
    return { image_points, world_points_m: points.map((p) => [p.X, p.Y] as [number, number]) };
  }

  async function apply() {
    error = "";
    result = null;
    applying = true;
    try {
      const payload: Parameters<typeof setScene>[1] = {};
      const cal = buildCalibration();
      if (cal) payload.calibration = cal;
      if (zones.length) {
        payload.zones = Object.fromEntries(
          zones.map((z) => [z.name, z.verts.map(([nx, ny]) => toImagePx(nx, ny))]),
        );
        payload.zone_directions = Object.fromEntries(zones.map((z) => [z.name, z.direction]));
      }
      if (stopLines.length) {
        payload.stop_lines = stopLines.map((sl) => ({
          approach: sl.approach,
          points: sl.verts.map(([nx, ny]) => toImagePx(nx, ny)),
        }));
      }
      result = await setScene(camera_id, payload);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      applying = false;
    }
  }

  const zoneColour = (dir: string) => (dir === "ns" ? "var(--color-ok)" : "var(--color-warn)");
</script>

<div class="modal" role="dialog" aria-modal="true">
  <div class="sheet">
    <header>
      <h2>Calibrate — {camera_id}</h2>
      <div class="tabs">
        <button class:active={mode === "points"} onclick={() => (mode = "points")}>Reference points</button>
        <button class:active={mode === "zones"} onclick={() => (mode = "zones")}>Approach zones</button>
        <button class:active={mode === "stoplines"} onclick={() => (mode = "stoplines")}>Stop-lines</button>
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
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions a11y_no_noninteractive_element_interactions a11y_missing_attribute -->
          <div class="stage" role="presentation" bind:clientWidth={stageW} bind:clientHeight={stageH} onclick={stageClick}>
            <img src={backdrop} alt="frame" bind:this={imgEl} />
            <svg viewBox="0 0 {stageW} {stageH}">
              {#each zones as z}
                <polygon points={z.verts.map(([nx, ny]) => `${px(nx, stageW)},${px(ny, stageH)}`).join(" ")}
                  style="fill:{zoneColour(z.direction)};stroke:{zoneColour(z.direction)}" fill-opacity="0.18" stroke-width="2.5" />
                <text x={px(z.verts[0][0], stageW)} y={px(z.verts[0][1], stageH) - 6} style="fill:{zoneColour(z.direction)}" font-size="15">{z.name}</text>
              {/each}
              {#if draft.length}
                <polyline points={draft.map(([nx, ny]) => `${px(nx, stageW)},${px(ny, stageH)}`).join(" ")} fill="none" style="stroke:var(--color-accent)" stroke-width="2.5" stroke-dasharray="8 6" />
                {#each draft as [nx, ny]}
                  <circle cx={px(nx, stageW)} cy={px(ny, stageH)} r="5" style="fill:var(--color-accent)" />
                {/each}
              {/if}
              {#each stopLines as sl}
                <line x1={px(sl.verts[0][0], stageW)} y1={px(sl.verts[0][1], stageH)}
                      x2={px(sl.verts[1][0], stageW)} y2={px(sl.verts[1][1], stageH)}
                      style="stroke:var(--color-critical)" stroke-width="3" />
                <text x={px(sl.verts[0][0], stageW)} y={px(sl.verts[0][1], stageH) - 6} style="fill:var(--color-critical)" font-size="14">stop · {sl.approach.toUpperCase()}</text>
              {/each}
              {#each slDraft as [nx, ny]}
                <circle cx={px(nx, stageW)} cy={px(ny, stageH)} r="5" style="fill:var(--color-critical)" />
              {/each}
              {#if mode === "points" && calMode === "rect" && points.length >= 2}
                <polyline
                  points={[...points, ...(points.length === 4 ? [points[0]] : [])].map((p) => `${px(p.nx, stageW)},${px(p.ny, stageH)}`).join(" ")}
                  fill="rgba(231,76,60,0.12)" style="stroke:var(--color-critical)" stroke-width="2" stroke-dasharray="6 5" />
              {/if}
              {#each points as p, i}
                <circle cx={px(p.nx, stageW)} cy={px(p.ny, stageH)} r="7" style="fill:var(--color-critical)" stroke="#fff" stroke-width="2" />
                <text x={px(p.nx, stageW) + 11} y={px(p.ny, stageH) - 9} fill="#fff" font-size="15">{i + 1}</text>
              {/each}
            </svg>
          </div>
        {/if}
        <p class="hint">
          {#if mode === "points" && calMode === "rect"}
            Click the <b>4 corners of a rectangle on the road</b> in order: near-left → near-right → far-right → far-left. Pick something whose real size you know — a crosswalk, a rectangular road marking, or a lane over a measured length. Then enter its width &amp; length.
          {:else if mode === "points"}
            Click ≥4 well-spread points on the road, then type each point's real-world position in metres (pick a fixed origin, e.g. a lane corner).
          {:else}
            Click to trace an approach zone's outline, name it, pick its direction, then “Finish zone”.
          {/if}
        </p>
      </div>

      <aside>
        {#if mode === "points"}
          <div class="calmode">
            <button class:active={calMode === "rect"} onclick={() => (calMode = "rect")}>Rectangle (easy)</button>
            <button class:active={calMode === "advanced"} onclick={() => (calMode = "advanced")}>Advanced</button>
          </div>

          {#if calMode === "rect"}
            <h3>Rectangle corners ({points.length}/4)</h3>
            <div class="list">
              {#each points as p, i}
                <div class="crow">
                  <span class="idx">{i + 1}</span>
                  <span class="cname">{["near-left", "near-right", "far-right", "far-left"][i]}</span>
                  <span class="px">{(p.nx * 100).toFixed(0)},{(p.ny * 100).toFixed(0)}%</span>
                  <button class="x" onclick={() => removePoint(i)}>✕</button>
                </div>
              {/each}
              {#if !points.length}<p class="empty">Click the 4 corners on the image.</p>{/if}
            </div>
            {#if points.length}<button class="clear" onclick={clearPoints}>Clear corners</button>{/if}
            <div class="rect-size">
              <label>Width (m)<input type="number" step="0.1" min="0" bind:value={rectW} placeholder="e.g. 3.5" /></label>
              <label>Length (m)<input type="number" step="0.1" min="0" bind:value={rectL} placeholder="e.g. 12" /></label>
            </div>
            <p class="tip">Width = across the road, Length = along it. A standard lane is ~3.5 m wide; measure the length with a map/odometer if you can.</p>
          {:else}
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
          {/if}
        {:else if mode === "zones"}
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
        {:else}
          <h3>Stop-lines ({stopLines.length})</h3>
          <p class="sub">Red-light-running detection</p>
          <div class="list">
            {#each stopLines as sl, i}
              <div class="zrow">
                <span class="dot" style="background:var(--color-critical)"></span>
                <span class="zname">stop-line {i + 1}</span>
                <span class="zdir">{sl.approach.toUpperCase()}</span>
                <button class="x" onclick={() => removeStopLine(i)}>✕</button>
              </div>
            {/each}
            {#if !stopLines.length}<p class="empty">Click 2 points across a lane to draw the stop-line.</p>{/if}
          </div>
          <div class="zbuild">
            <div class="dirs">
              <button class:active={slDir === "ns"} onclick={() => (slDir = "ns")}>N–S</button>
              <button class:active={slDir === "ew"} onclick={() => (slDir = "ew")}>E–W</button>
            </div>
            <p class="tip">Pick the approach direction, then click the two ends of its stop-line. A vehicle crossing it on red is flagged.</p>
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
  .sheet { width: min(1200px, 94vw); height: min(800px, 92vh); background: var(--color-surface-1); border: 1px solid var(--color-border); border-radius: 10px; display: flex; flex-direction: column; overflow: hidden; }
  header { display: flex; align-items: center; gap: 16px; padding: 12px 16px; border-bottom: 1px solid var(--color-border); }
  header h2 { margin: 0; font-size: 1rem; }
  .tabs { display: flex; gap: 6px; margin-left: 8px; }
  .tabs button, .dirs button { padding: 6px 12px; background: var(--color-surface-2); border: 1px solid var(--color-border); color: var(--color-muted); border-radius: 6px; cursor: pointer; font-size: 0.8rem; }
  .tabs button.active, .dirs button.active { background: var(--color-surface-3); border-color: var(--color-accent-dim); color: var(--color-accent); }
  .close { margin-left: auto; background: none; border: none; color: var(--color-muted); font-size: 1.1rem; cursor: pointer; }
  .content { flex: 1; display: grid; grid-template-columns: 1fr 320px; min-height: 0; }
  .stage-wrap { padding: 14px; display: flex; flex-direction: column; align-items: center; min-height: 0; }
  /* The stage shrinks to the rendered image (any aspect/orientation), so the
     click overlay and the image share exactly the same box — clicks always
     land under the cursor. */
  .stage { position: relative; display: inline-block; line-height: 0; background: var(--color-surface-1); border-radius: 6px; overflow: hidden; cursor: crosshair; }
  .stage img { display: block; width: auto; height: auto; max-width: 100%; max-height: 64vh; }
  .stage svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .hint { font-size: 0.78rem; color: var(--color-muted); margin: 10px 2px 0; line-height: 1.4; }
  .err-box { display: grid; place-items: center; aspect-ratio: 16/9; color: var(--color-muted); background: var(--color-surface-1); border-radius: 6px; }
  aside { border-left: 1px solid var(--color-border); padding: 14px; display: flex; flex-direction: column; overflow: auto; }
  aside h3 { margin: 0 0 2px; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-muted); }
  .sub { margin: 0 0 8px; font-size: 0.7rem; color: var(--color-dim); }
  .list { display: flex; flex-direction: column; gap: 6px; }
  .calmode { display: flex; gap: 6px; margin-bottom: 12px; }
  .calmode button { flex: 1; padding: 6px; background: var(--color-surface-2); border: 1px solid var(--color-border); color: var(--color-muted); border-radius: 6px; cursor: pointer; font-size: 0.76rem; }
  .calmode button.active { background: var(--color-surface-3); border-color: var(--color-accent-dim); color: var(--color-accent); }
  .crow { display: grid; grid-template-columns: 18px 1fr auto 22px; gap: 8px; align-items: center; font-size: 0.8rem; }
  .crow .cname { color: var(--color-text); }
  .clear { margin: 8px 0; padding: 6px; background: var(--color-surface-2); border: 1px solid var(--color-border); color: var(--color-muted); border-radius: 5px; cursor: pointer; font-size: 0.74rem; }
  .rect-size { display: flex; gap: 8px; margin-top: 10px; }
  .rect-size label { flex: 1; display: flex; flex-direction: column; gap: 3px; font-size: 0.72rem; color: var(--color-muted); }
  .rect-size input { padding: 6px 8px; background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: 5px; color: var(--color-text); font-size: 0.85rem; }
  .tip { margin: 10px 0 0; font-size: 0.7rem; color: var(--color-muted); line-height: 1.4; }
  .row { display: grid; grid-template-columns: 20px 60px 1fr 1fr 22px; gap: 6px; align-items: center; }
  .row .idx { color: var(--color-critical); font-weight: 600; font-size: 0.8rem; }
  .row .px { font-size: 0.72rem; color: var(--color-dim); }
  .row input { width: 100%; padding: 4px 6px; background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: 4px; color: var(--color-text); font-size: 0.78rem; }
  .zrow { display: grid; grid-template-columns: 12px 1fr auto 22px; gap: 8px; align-items: center; font-size: 0.82rem; }
  .zrow .dot { width: 10px; height: 10px; border-radius: 50%; }
  .zrow .zdir { font-size: 0.7rem; color: var(--color-muted); }
  .x { background: none; border: none; color: var(--color-muted); cursor: pointer; }
  .zbuild { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
  .zbuild input { padding: 7px 9px; background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: 5px; color: var(--color-text); font-size: 0.82rem; }
  .dirs { display: flex; gap: 6px; }
  .dirs button { flex: 1; }
  .finish { padding: 7px; background: var(--color-surface-3); border: 1px solid var(--color-accent-dim); color: var(--color-accent); border-radius: 5px; cursor: pointer; }
  .finish:disabled { opacity: 0.5; cursor: default; }
  .empty { color: var(--color-dim); font-size: 0.8rem; }
  .apply { margin-top: auto; padding: 10px; background: var(--color-accent-dim); border: none; border-radius: 6px; color: #fff; font-weight: 600; cursor: pointer; }
  .apply:disabled { opacity: 0.6; }
  .apply-err { color: var(--color-critical); font-size: 0.76rem; }
  .apply-ok { color: var(--color-ok); font-size: 0.76rem; }
</style>
