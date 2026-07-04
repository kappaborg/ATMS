<script lang="ts">
  import { onMount } from "svelte";
  import { connectData, listCameras, downloadReport } from "./lib/gateway";
  import type { CameraInfo, FrameEvent } from "./lib/types";
  import MetricsBar from "./components/MetricsBar.svelte";
  import CameraTile from "./components/CameraTile.svelte";
  import DecisionPanel from "./components/DecisionPanel.svelte";
  import CameraManager from "./components/CameraManager.svelte";
  import CalibrationOverlay from "./components/CalibrationOverlay.svelte";

  let events = $state<Record<string, FrameEvent>>({});
  let cameras = $state<CameraInfo[]>([]);
  let connected = $state(false);
  let selected = $state<string | null>(null);
  let dataHz = $state(0);
  let calibrating = $state<string | null>(null);

  let eventCount = 0;

  async function refresh() {
    try {
      cameras = await listCameras();
      if (!selected && cameras.length) selected = cameras[0].camera_id;
    } catch {
      /* gateway offline; MetricsBar shows it */
    }
  }

  onMount(() => {
    refresh();
    const stopData = connectData(
      (e) => {
        events = { ...events, [e.camera_id]: e };
        eventCount++;
        if (!selected) selected = e.camera_id;
      },
      (c) => (connected = c),
    );
    const poll = setInterval(refresh, 3000);
    const hz = setInterval(() => {
      dataHz = eventCount;
      eventCount = 0;
    }, 1000);
    return () => {
      stopData();
      clearInterval(poll);
      clearInterval(hz);
    };
  });

  const selectedEvent = $derived(selected ? events[selected] : undefined);
</script>

<main>
  <MetricsBar {events} {connected} {dataHz} />
  <div class="body">
    <div class="grid" style="--cols:{cameras.length <= 1 ? 1 : 2}">
      {#each cameras as cam (cam.camera_id)}
        <div class="cell" class:sel={selected === cam.camera_id} onclick={() => (selected = cam.camera_id)} role="button" tabindex="0">
          <CameraTile camera_id={cam.camera_id} event={events[cam.camera_id]} live={cam.live} kind={cam.kind} />
        </div>
      {:else}
        <div class="hint">
          <h1>No cameras</h1>
          <p>Add an RTSP stream, a USB device, or a video file to begin.</p>
        </div>
      {/each}
    </div>
    <aside>
      {#if selected}
        <div class="sel-bar">
          <span>{selected}</span>
          <div class="sel-actions">
            <button onclick={() => downloadReport(selected!)} title="Export session report (CSV)">⤓ Report</button>
            <button onclick={() => (calibrating = selected)}>⚙ Calibrate</button>
          </div>
        </div>
      {/if}
      <DecisionPanel event={selectedEvent} />
      <CameraManager onchange={refresh} />
    </aside>
  </div>

  {#if calibrating}
    <CalibrationOverlay
      camera_id={calibrating}
      onclose={() => {
        calibrating = null;
        refresh();
      }}
    />
  {/if}
</main>

<style>
  main { display: flex; flex-direction: column; height: 100vh; }
  .body { flex: 1; display: grid; grid-template-columns: 1fr 300px; min-height: 0; }
  .grid { display: grid; grid-template-columns: repeat(var(--cols), 1fr); gap: 12px; padding: 12px; align-content: start; overflow: auto; }
  .cell { cursor: pointer; border-radius: 8px; outline: 2px solid transparent; transition: outline-color .15s; }
  .cell.sel { outline-color: #2b6ea3; }
  aside { border-left: 1px solid #1e2230; background: #0a0c11; overflow: auto; display: flex; flex-direction: column; }
  .sel-bar { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; border-bottom: 1px solid #1e2230; font-size: 0.85rem; color: #cfe8ff; }
  .sel-actions { display: flex; gap: 6px; }
  .sel-bar button { background: #1b3a52; border: 1px solid #2b6ea3; color: #cfe8ff; border-radius: 5px; padding: 5px 10px; cursor: pointer; font-size: 0.78rem; }
  .hint { grid-column: 1 / -1; display: grid; place-content: center; text-align: center; color: #667; }
  .hint h1 { font-size: 1.1rem; color: #8b95a7; margin: 0 0 6px; }
  .hint p { font-size: 0.85rem; margin: 0; }
</style>
