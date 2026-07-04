<script lang="ts">
  import { onMount } from "svelte";
  import { connectData, listCameras, listIntersections, listCorridors, downloadReport, authRequired, getMe, logout, getHistory, setSahi, type Me, type HistoryTotals } from "./lib/gateway";
  import type { CameraInfo, FrameEvent, IntersectionInfo, Corridor } from "./lib/types";
  import MetricsBar from "./components/MetricsBar.svelte";
  import CameraTile from "./components/CameraTile.svelte";
  import DecisionPanel from "./components/DecisionPanel.svelte";
  import CameraManager from "./components/CameraManager.svelte";
  import CalibrationOverlay from "./components/CalibrationOverlay.svelte";
  import NetworkOverview from "./components/NetworkOverview.svelte";
  import CorridorsPanel from "./components/CorridorsPanel.svelte";
  import ViolationsLog from "./components/ViolationsLog.svelte";
  import Login from "./components/Login.svelte";

  let events = $state<Record<string, FrameEvent>>({});
  let cameras = $state<CameraInfo[]>([]);
  let intersections = $state<IntersectionInfo[]>([]);
  let corridors = $state<Corridor[]>([]);
  let view = $state<"overview" | "cameras" | "violations">("cameras");
  let activeIntersection = $state<string | null>(null);
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

  let history30 = $state<HistoryTotals | null>(null);

  async function refresh() {
    try {
      cameras = await listCameras();
      intersections = await listIntersections();
      corridors = await listCorridors();
      if (!selected && cameras.length) selected = cameras[0].camera_id;
      history30 = selected ? await getHistory(selected, 720) : null; // last 30 days
    } catch {
      /* gateway offline or token expired; MetricsBar shows it */
    }
  }

  const shownCameras = $derived(
    activeIntersection ? cameras.filter((c) => c.intersection_id === activeIntersection) : cameras,
  );
  const selectedCam = $derived(cameras.find((c) => c.camera_id === selected));

  async function toggleSahi() {
    if (!selected || !selectedCam) return;
    try {
      await setSahi(selected, !selectedCam.sahi);
      await refresh();
    } catch {
      /* gateway offline */
    }
  }

  function openIntersection(id: string) {
    activeIntersection = id;
    view = "cameras";
    const first = cameras.find((c) => c.intersection_id === id);
    if (first) selected = first.camera_id;
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
  <div class="topbar">
    <div class="viewtabs">
      <button class:on={view === "overview"} onclick={() => { view = "overview"; activeIntersection = null; }}>Network</button>
      <button class:on={view === "cameras"} onclick={() => (view = "cameras")}>Cameras</button>
      <button class:on={view === "violations"} onclick={() => (view = "violations")}>Violations</button>
      {#if view === "cameras" && activeIntersection}
        <span class="crumb">Intersection {activeIntersection}
          <button class="clr" onclick={() => (activeIntersection = null)}>× all</button>
        </span>
      {/if}
    </div>
    {#if me}
      <span class="userbar"><b>{me.username}</b> · <span class="role role-{me.role}">{me.role}</span>
        <button onclick={signOut}>Sign out</button></span>
    {/if}
  </div>

  {#if view === "overview"}
    <div class="overview-scroll">
      <NetworkOverview {intersections} {events} onselect={openIntersection} />
      <CorridorsPanel {corridors} {intersections} {canOperate} onchange={refresh} />
    </div>
  {:else if view === "violations"}
    <ViolationsLog />
  {:else}
  <div class="body">
    <div class="grid" style="--cols:{shownCameras.length <= 1 ? 1 : 2}">
      {#each shownCameras as cam (cam.camera_id)}
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
              <button class:sahion={selectedCam?.sahi} onclick={toggleSahi}
                title="SAHI sliced inference: detects small/distant objects (aerial views) but is slower. Enable per camera only where needed.">
                🔬 SAHI {selectedCam?.sahi ? "ON" : "off"}
              </button>
              <button onclick={() => (calibrating = selected)}>⚙ Calibrate</button>
            {/if}
          </div>
        </div>
      {/if}
      <DecisionPanel event={selectedEvent} camera_id={selected} {canOperate} {history30} />
      {#if canOperate}
        <CameraManager onchange={refresh} />
      {:else}
        <p class="readonly">Viewer role — monitoring only. Camera and calibration controls require an operator account.</p>
      {/if}
    </aside>
  </div>
  {/if}

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
  .overview-scroll { flex: 1; overflow: auto; min-height: 0; }
  .topbar { display: flex; align-items: center; justify-content: space-between; padding: 4px 12px; background: #0a0c11; border-bottom: 1px solid #1e2230; }
  .viewtabs { display: flex; align-items: center; gap: 4px; }
  .viewtabs button { background: none; border: 1px solid transparent; color: #8b95a7; border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 0.78rem; }
  .viewtabs button.on { background: #12202e; border-color: #2b6ea3; color: #cfe8ff; }
  .crumb { font-size: 0.72rem; color: #8b95a7; margin-left: 8px; }
  .crumb .clr { background: none; border: none; color: #6b7688; cursor: pointer; font-size: 0.72rem; padding: 0 4px; }
  .userbar { display: flex; align-items: center; gap: 10px; font-size: 0.74rem; color: #9aa4b2; }
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
  .sel-bar button.sahion { background: #1b5233; border-color: #2ecc71; color: #d6ffe6; }
  .hint { grid-column: 1 / -1; display: grid; place-content: center; text-align: center; color: #667; }
  .hint h1 { font-size: 1.1rem; color: #8b95a7; margin: 0 0 6px; }
  .hint p { font-size: 0.85rem; margin: 0; }
</style>
