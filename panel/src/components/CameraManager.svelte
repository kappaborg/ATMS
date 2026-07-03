<script lang="ts">
  import { addCamera, listDevices, type VideoDevice } from "../lib/gateway";
  let { onchange }: { onchange: () => void } = $props();

  let camId = $state("");
  let source = $state("");
  let kind = $state<"rtsp" | "usb" | "file">("rtsp");
  let busy = $state(false);
  let error = $state("");

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
    busy = true;
    try {
      await addCamera(camId.trim(), source.trim(), kind === "file");
      camId = ""; source = "";
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
  form { padding: 14px 16px; border-top: 1px solid #1e2230; display: flex; flex-direction: column; gap: 8px; }
  h2 { margin: 0 0 4px; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.06em; color: #8b95a7; }
  .detect { padding: 6px; background: #12151d; border: 1px solid #2b6ea3; color: #7fd1ff; border-radius: 5px; cursor: pointer; font-size: 0.76rem; }
  .detect:disabled { opacity: 0.6; }
  .devs { display: flex; flex-wrap: wrap; gap: 6px; }
  .dev { padding: 5px 8px; background: #1b3a52; border: 1px solid #2b6ea3; color: #cfe8ff; border-radius: 5px; cursor: pointer; font-size: 0.72rem; }
  .kinds { display: flex; gap: 6px; }
  .kinds button { flex: 1; padding: 5px; background: #12151d; border: 1px solid #1e2230; color: #9aa4b2; border-radius: 5px; cursor: pointer; font-size: 0.72rem; }
  .kinds button.active { background: #1b3a52; border-color: #2b6ea3; color: #cfe8ff; }
  input { padding: 8px 10px; background: #12151d; border: 1px solid #1e2230; border-radius: 5px; color: #eaf1f8; font-size: 0.82rem; }
  input::placeholder { color: #5a6478; }
  .add { padding: 8px; background: #2b6ea3; border: none; border-radius: 5px; color: #fff; cursor: pointer; font-weight: 600; }
  .add:disabled { opacity: 0.6; }
  .err { color: #e74c3c; font-size: 0.75rem; margin: 0; }
</style>
