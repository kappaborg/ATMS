<script lang="ts">
  import { onMount } from "svelte";
  import { connectData, listCameras, downloadReport, authRequired, getMe, logout, type Me } from "./lib/gateway";
  import type { CameraInfo, FrameEvent } from "./lib/types";
  import MetricsBar from "./components/MetricsBar.svelte";
  import CameraTile from "./components/CameraTile.svelte";
  import DecisionPanel from "./components/DecisionPanel.svelte";
  import CameraManager from "./components/CameraManager.svelte";
  import CalibrationOverlay from "./components/CalibrationOverlay.svelte";
  import Login from "./components/Login.svelte";

  let events = $state<Record<string, FrameEvent>>({});
  let cameras = $state<CameraInfo[]>([]);
  let connected = $state(false);
  let selected = $state<string | null>(null);
  let dataHz = $state(0);
  let calibrating = $state<string | null>(null);

  let authReq = $state(false);
  let me = $state<Me | null>(null);
  let ready = $state(false);
  let stopFns: (() => void)[] = [];
  let eventCount = 0;

  // Operators/admins can mutate; viewers (and auth-disabled dev) accordingly.
  const canOperate = $derived(!authReq || me?.role === "operator" || me?.role === "admin");

  async function refresh() {
    try {
      cameras = await listCameras();
      if (!selected && cameras.length) selected = cameras[0].camera_id;
    } catch {
      /* gateway offline or token expired; MetricsBar shows it */
    }
  }

  function start() {
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
    stopFns = [stopData, () => clearInterval(poll), () => clearInterval(hz)];
  }

  function onAuthed(m: Me) {
    me = m;
    start();
  }

  function signOut() {
    logout();
    stopFns.forEach((f) => f());
    stopFns = [];
    events = {};
    cameras = [];
    selected = null;
    me = null;
  }

  onMount(async () => {
    authReq = await authRequired();
    if (authReq) {
      me = await getMe(); // resume a valid stored session
      if (me) start();
    } else {
      start(); // auth disabled (local dev)
    }
    ready = true;
    return () => stopFns.forEach((f) => f());
  });

  const selectedEvent = $derived(selected ? events[selected] : undefined);
</script>

{#if ready && authReq && !me}
  <Login onauth={onAuthed} />
{:else}
<main>
  <MetricsBar {events} {connected} {dataHz} />
  {#if me}
    <div class="userbar">
      <span class="who"><b>{me.username}</b> · <span class="role role-{me.role}">{me.role}</span></span>
      <button onclick={signOut}>Sign out</button>
    </div>
  {/if}
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
            {#if canOperate}
              <button onclick={() => (calibrating = selected)}>⚙ Calibrate</button>
            {/if}
          </div>
        </div>
      {/if}
      <DecisionPanel event={selectedEvent} camera_id={selected} {canOperate} />
      {#if canOperate}
        <CameraManager onchange={refresh} />
      {:else}
        <p class="readonly">Viewer role — monitoring only. Camera and calibration controls require an operator account.</p>
      {/if}
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
{/if}

<style>
  main { display: flex; flex-direction: column; height: 100vh; }
  .userbar { display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding: 4px 16px; background: #0a0c11; border-bottom: 1px solid #1e2230; font-size: 0.74rem; color: #9aa4b2; }
  .userbar .role { text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.66rem; padding: 1px 6px; border-radius: 4px; background: #1a2331; }
  .userbar .role-admin { color: #f1c40f; }
  .userbar .role-operator { color: #7fd1ff; }
  .userbar .role-viewer { color: #7fd6a0; }
  .userbar button { background: none; border: 1px solid #2b3547; color: #9aa4b2; border-radius: 5px; padding: 3px 10px; cursor: pointer; font-size: 0.72rem; }
  .readonly { margin: 12px 16px; padding: 10px 12px; background: #0e1622; border: 1px solid #1e2230; border-radius: 8px; font-size: 0.74rem; color: #7fd6a0; line-height: 1.4; }
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
