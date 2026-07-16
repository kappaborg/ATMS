<script lang="ts">
  import { addCamera, setJunction, listDevices, type VideoDevice } from "../lib/gateway";
  import { APPROACHES, APPROACH_LABEL, isNamed, junctionLabel } from "../lib/naming";
  import type { Approach, IntersectionInfo } from "../lib/types";

  let { onchange, intersections = [] }: { onchange: () => void; intersections?: IntersectionInfo[] } = $props();

  const NEW = "__new";

  let camId = $state("");
  let source = $state("");
  let kind = $state<"rtsp" | "usb" | "file">("rtsp");
  let busy = $state(false);
  let error = $state("");

  // Which junction this camera watches, and where on it.
  let junction = $state("");
  let newId = $state("");
  let city = $state("");
  let jname = $state("");
  let approach = $state<Approach | "">("");

  // Default to the first junction so the common case (a second camera on an
  // existing junction) needs no thought; only an empty network starts on "new".
  // Tracks `picked` rather than testing `junction` for emptiness: the list
  // arrives after first render, so an emptiness guard would latch the initial
  // "new" and never fall back to a real junction once one loaded.
  let picked = $state(false);
  $effect(() => {
    if (!picked) junction = intersections[0]?.intersection_id ?? NEW;
  });

  const targetId = $derived(junction === NEW ? newId.trim() : junction);
  const current = $derived(intersections.find((i) => i.intersection_id === targetId));
  // Ask for a place name only when we don't already have one — naming an
  // already-named junction from the add-camera form would silently rename it
  // for every other camera on it.
  const needsName = $derived(!isNamed(current));

  let devices = $state<VideoDevice[]>([]);
  let detecting = $state(false);

  async function detect() {
    detecting = true;
    error = "";
    try {
      devices = await listDevices();
      if (!devices.length) error = "no cameras found (grant camera permission, connect iPhone)";
    } catch (err) {
      error = (err as Error).message;
    } finally {
      detecting = false;
    }
  }

  const placeholder = $derived(
    kind === "rtsp" ? "rtsp://user:pass@192.168.1.10:554/stream"
    : kind === "usb" ? "0   (device index)"
    : "videos/T1.mp4   (path on the gateway host)"
  );

  async function submit(e: Event) {
    e.preventDefault();
    error = "";
    if (!camId || !source) { error = "camera id and source are required"; return; }
    if (!targetId) { error = "pick a junction, or give the new one an id"; return; }
    busy = true;
    try {
      // Name the junction first: if adding the camera fails, the operator keeps
      // the name they typed rather than having to retype it.
      if (city.trim() || jname.trim()) await setJunction(targetId, jname, city);
      await addCamera(camId.trim(), source.trim(), kind === "file", {
        intersection_id: targetId,
        approach: approach || null,
      });
      camId = ""; source = ""; approach = ""; city = ""; jname = "";
      if (junction === NEW) { junction = targetId; newId = ""; }
      onchange();
    } catch (err) {
      error = (err as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<form onsubmit={submit}>
  <h2>Add camera</h2>
  <div class="kinds">
    {#each ["rtsp", "usb", "file"] as k}
      <button type="button" class:active={kind === k} onclick={() => (kind = k as typeof kind)}>{k.toUpperCase()}</button>
    {/each}
  </div>
  <input placeholder="camera id (e.g. north-approach)" bind:value={camId} />
  <input placeholder={placeholder} bind:value={source} />

  <div class="where">
    <select bind:value={junction} onchange={() => (picked = true)} aria-label="Junction">
      {#each intersections as it}
        <option value={it.intersection_id}>{junctionLabel(it)}</option>
      {/each}
      <option value={NEW}>New junction…</option>
    </select>
    <select bind:value={approach} aria-label="Approach">
      <option value="">approach…</option>
      {#each APPROACHES as a}<option value={a}>{APPROACH_LABEL[a]}</option>{/each}
    </select>
  </div>
  {#if junction === NEW}
    <input placeholder="junction id (e.g. 2)" bind:value={newId} />
  {/if}
  {#if needsName}
    <div class="where">
      <input placeholder="city (e.g. Sarajevo)" bind:value={city} />
      <input placeholder="junction (e.g. Marijin Dvor)" bind:value={jname} />
    </div>
    <p class="hint">Naming the junction is what makes the map readable — cameras show as “{city.trim() || "Sarajevo"} · {jname.trim() || "Marijin Dvor"} · North”.</p>
  {/if}
  {#if kind === "usb"}
    <button type="button" class="detect" onclick={detect} disabled={detecting}>
      {detecting ? "detecting…" : "Detect cameras (incl. iPhone)"}
    </button>
    {#if devices.length}
      <div class="devs">
        {#each devices as d}
          <button type="button" class="dev" onclick={() => (source = String(d.index))}>
            #{d.index} · {d.width}×{d.height}
          </button>
        {/each}
      </div>
    {/if}
  {/if}
  {#if error}<p class="err">{error}</p>{/if}
  <button type="submit" class="add" disabled={busy}>{busy ? "adding…" : "Add"}</button>
</form>

<style>
  form { padding: 14px 16px; border-top: 1px solid var(--color-border); display: flex; flex-direction: column; gap: 8px; }
  h2 { margin: 0 0 4px; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-muted); }
  .where { display: flex; gap: 8px; }
  .where > * { flex: 1; min-width: 0; }
  .hint { margin: 0; font-size: 0.7rem; line-height: 1.4; color: var(--color-dim); }
  .detect { padding: 6px; background: var(--color-surface-2); border: 1px solid var(--color-accent-dim); color: var(--color-accent); border-radius: 5px; cursor: pointer; font-size: 0.76rem; }
  .detect:disabled { opacity: 0.6; }
  .devs { display: flex; flex-wrap: wrap; gap: 6px; }
  .dev { padding: 5px 8px; background: var(--color-surface-3); border: 1px solid var(--color-accent-dim); color: var(--color-accent); border-radius: 5px; cursor: pointer; font-size: 0.72rem; }
  .kinds { display: flex; gap: 6px; }
  .kinds button { flex: 1; padding: 5px; background: var(--color-surface-2); border: 1px solid var(--color-border); color: var(--color-muted); border-radius: 5px; cursor: pointer; font-size: 0.72rem; }
  .kinds button.active { background: var(--color-surface-3); border-color: var(--color-accent-dim); color: var(--color-accent); }
  input, select { padding: 8px 10px; background: var(--color-surface-2); border: 1px solid var(--color-border-2); border-radius: 5px; color: var(--color-text); font-size: 0.82rem; font-family: inherit; }
  select { cursor: pointer; }
  input::placeholder { color: var(--color-dim); }
  .add { padding: 8px; background: var(--color-accent); border: none; border-radius: 5px; color: #fff; cursor: pointer; font-weight: 600; }
  .add:hover:not(:disabled) { background: var(--color-accent-dim); }
  .add:disabled { opacity: 0.6; }
  .err { color: var(--color-critical); font-size: 0.75rem; margin: 0; }
</style>
