<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { connectData, listCameras, listIntersections, listCorridors, downloadReport, authRequired, getMe, logout, getHistory, setSahi, setConfidence, type Me, type HistoryTotals } from "./lib/gateway";
  import type { CameraInfo, FrameEvent, IntersectionInfo, Corridor } from "./lib/types";
  import { cameraLabel } from "./lib/naming";
  import CameraTile from "./components/CameraTile.svelte";
  import DecisionPanel from "./components/DecisionPanel.svelte";
  import CameraManager from "./components/CameraManager.svelte";
  import CalibrationOverlay from "./components/CalibrationOverlay.svelte";
  import Overview from "./components/Overview.svelte";
  import CorridorsPanel from "./components/CorridorsPanel.svelte";
  import ViolationsLog from "./components/ViolationsLog.svelte";
  import Login from "./components/Login.svelte";
  import ThemeToggle from "./components/ThemeToggle.svelte";
  import Icon from "./components/Icon.svelte";

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
  // Newest frame per camera, buffered off the reactive graph. The WS delivers
  // ~30-35 fps; re-rendering every metric that fast makes the numbers flicker.
  // We flush this buffer into `events` on a calm cadence instead.
  let latest: Record<string, FrameEvent> = {};

  // Operators/admins can mutate; viewers (and auth-disabled dev) accordingly.
  const canOperate = $derived(!authReq || me?.role === "operator" || me?.role === "admin");

  // Place name where the junction has been named; the raw id is kept on the
  // title attribute, since that is still what the operator types into configs.
  const selectedLabel = $derived.by(() => {
    const cam = cameras.find((c) => c.camera_id === selected);
    return cam ? cameraLabel(cam, intersections) : (selected ?? "");
  });

  let history30 = $state<HistoryTotals | null>(null);

  async function refresh() {
    try {
      cameras = await listCameras();
      // Drop buffered/stored frames for cameras that no longer exist, so the
      // Overview KPIs and live charts stop counting removed cameras.
      const ids = new Set(cameras.map((c) => c.camera_id));
      for (const k of Object.keys(events)) if (!ids.has(k)) delete events[k];
      for (const k of Object.keys(latest)) if (!ids.has(k)) delete latest[k];
      intersections = await listIntersections();
      corridors = await listCorridors();
      if (!selected && cameras.length) selected = cameras[0].camera_id;
      history30 = selected ? await getHistory(selected, 720) : null; // last 30 days
    } catch {
      /* gateway offline or token expired; the status bar shows it */
    }
  }

  const shownCameras = $derived(
    activeIntersection ? cameras.filter((c) => c.intersection_id === activeIntersection) : cameras,
  );
  const selectedCam = $derived(cameras.find((c) => c.camera_id === selected));
  const liveCount = $derived(cameras.filter((c) => c.live).length);

  async function toggleSahi() {
    if (!selected || !selectedCam) return;
    try {
      await setSahi(selected, !selectedCam.sahi);
      await refresh();
    } catch {
      /* gateway offline */
    }
  }

  async function bumpConfidence(delta: number) {
    if (!selected || !selectedCam) return;
    const next = Math.min(0.95, Math.max(0.05, Math.round((selectedCam.min_confidence + delta) * 100) / 100));
    try {
      await setConfidence(selected, next);
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

  // Panel metrics refresh at this cadence (ms). The video stays real-time; only
  // the numeric/decision readouts are throttled so they're calm and readable.
  const DISPLAY_MS = 500;

  function start() {
    refresh();
    const stopData = connectData(
      (e) => {
        latest[e.camera_id] = e; // buffer only — no re-render on the raw stream
        eventCount++;
        if (!selected) selected = e.camera_id;
      },
      (c) => (connected = c),
    );
    // Flush the newest buffered frames into reactive state a few times a second,
    // then empty the buffer so we only re-render when fresh frames actually arrive.
    const flush = setInterval(() => {
      if (Object.keys(latest).length) {
        events = { ...events, ...latest };
        latest = {};
      }
    }, DISPLAY_MS);
    const poll = setInterval(refresh, 3000);
    const hz = setInterval(() => {
      dataHz = eventCount;
      eventCount = 0;
    }, 1000);
    stopFns = [stopData, () => clearInterval(flush), () => clearInterval(poll), () => clearInterval(hz)];
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
    latest = {};
    cameras = [];
    selected = null;
    me = null;
  }

  // NOTE: an async onMount's returned cleanup is IGNORED by Svelte — use a
  // sync onMount + onDestroy so the sockets/intervals are actually torn down.
  onMount(() => {
    (async () => {
      authReq = await authRequired();
      if (authReq) {
        me = await getMe(); // resume a valid stored session
        if (me) start();
      } else {
        start(); // auth disabled (local dev)
      }
      ready = true;
    })();
  });
  onDestroy(() => stopFns.forEach((f) => f()));

  const selectedEvent = $derived(selected ? events[selected] : undefined);

  const NAV: { id: typeof view; label: string }[] = [
    { id: "overview", label: "Home" },
    { id: "cameras", label: "Cameras" },
    { id: "violations", label: "Alerts" },
  ];
  function go(id: typeof view) {
    view = id;
    if (id === "overview") activeIntersection = null;
  }
</script>

{#if ready && authReq && !me}
  <Login onauth={onAuthed} />
{:else}
<div class="app">
  <header class="topbar">
    <div class="brand">
      <div class="mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2">
          <rect x="8" y="2.5" width="8" height="19" rx="3.5" />
          <circle cx="12" cy="7" r="1.4" fill="#fff" stroke="none" />
          <circle cx="12" cy="12" r="1.4" fill="#fff" stroke="none" />
          <circle cx="12" cy="17" r="1.4" fill="#fff" stroke="none" />
        </svg>
      </div>
      <div class="wordmark"><b>ATMS</b> <span>City Traffic</span></div>
    </div>

    <div class="pills">
      <span class="pill"><span class="dot" class:on={connected} class:off={!connected}></span>{connected ? "Connected" : "Offline"}</span>
      <span class="pill"><span class="num">{liveCount}</span>/{cameras.length} cameras</span>
    </div>

    <div class="spacer"></div>
    <ThemeToggle />
    {#if me}
      <div class="op">
        <div class="ava">{me.username.slice(0, 2).toUpperCase()}</div>
        <div class="who"><b>{me.username}</b><i class="role-{me.role}">{me.role}</i></div>
        <button class="signout" onclick={signOut}>Sign out</button>
      </div>
    {/if}
  </header>

  <nav class="rail">
    {#each NAV as item (item.id)}
      <button class="nav" class:on={view === item.id} onclick={() => go(item.id)}>
        {#if item.id === "overview"}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></svg>
        {:else if item.id === "cameras"}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="7" width="14" height="11" rx="2.5" /><path d="M17 11l4-2v6l-4-2z" /></svg>
        {:else}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l9 16H3z" /><path d="M12 10v4" /><circle cx="12" cy="16.5" r=".7" fill="currentColor" /></svg>
        {/if}
        <span>{item.label}</span>
      </button>
    {/each}
    <div class="grow"></div>
    <div class="tip">Junctions adapt in real time. <b>Safety back-up on.</b></div>
  </nav>

  <main class="content">
    {#if view === "overview"}
      <div class="scroll">
        <Overview {intersections} {events} {cameras} onselect={openIntersection} />
        <CorridorsPanel {corridors} {intersections} {canOperate} onchange={refresh} />
      </div>
    {:else if view === "violations"}
      <ViolationsLog {canOperate} />
    {:else}
      <div class="cams">
        {#if activeIntersection}
          <div class="crumb">Intersection {activeIntersection}
            <button onclick={() => (activeIntersection = null)}>× show all</button>
          </div>
        {/if}
        <div class="body">
          <div class="grid">
            {#each shownCameras as cam (cam.camera_id)}
              <div class="cell" class:sel={selected === cam.camera_id} onclick={() => (selected = cam.camera_id)}
                onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (selected = cam.camera_id)} role="button" tabindex="0">
                <CameraTile camera_id={cam.camera_id} event={events[cam.camera_id]} live={cam.live} kind={cam.kind} {canOperate} />
              </div>
            {:else}
              <div class="hint">
                <h1>No cameras yet</h1>
                <p>Add a street camera — a link, a USB device, or a video file — to begin.</p>
              </div>
            {/each}
          </div>
          <aside class="dock">
            {#if selected}
              <div class="sel-bar">
                <span title={selected}>{selectedLabel}</span>
                <div class="sel-actions">
                  <button onclick={() => downloadReport(selected!)} title="Export session report (CSV)"><Icon name="download" size={14} />Report</button>
                  {#if canOperate}
                    <span class="conf" title="Detection confidence floor. Raise it to remove wrong boxes on noisy scenes; lower it for recall on dim/small objects.">
                      <button onclick={() => bumpConfidence(-0.05)}>−</button>
                      <span class="confval">conf {(selectedCam?.min_confidence ?? 0.35).toFixed(2)}</span>
                      <button onclick={() => bumpConfidence(0.05)}>+</button>
                    </span>
                    <button class:sahion={selectedCam?.sahi} onclick={toggleSahi}
                      title="SAHI sliced inference: detects small/distant objects but is slower. Enable per camera only where needed.">
                      SAHI {selectedCam?.sahi ? "ON" : "off"}
                    </button>
                    <button onclick={() => (calibrating = selected)}><Icon name="gear" size={14} />Calibrate</button>
                  {/if}
                </div>
              </div>
            {/if}
            <DecisionPanel event={selectedEvent} camera_id={selected} {canOperate} {history30} />
            {#if canOperate}
              <CameraManager onchange={refresh} {intersections} />
            {:else}
              <p class="readonly">Viewer role — monitoring only. Camera and calibration controls require an operator account.</p>
            {/if}
          </aside>
        </div>
      </div>
    {/if}
  </main>

  <footer class="statusbar">
    <span class="s"><span class="dot" class:on={connected} class:off={!connected}></span>{connected ? "Connected to gateway" : "Gateway offline"}</span>
    <span class="s">Watching <b>{intersections.length} {intersections.length === 1 ? "junction" : "junctions"}</b></span>
    <span class="s"><b>{dataHz}</b> updates/s</span>
    <span class="spacer"></span>
    {#if me}<span class="s">Signed in as <b>{me.username}</b></span>{/if}
    <span class="s">Safety back-up <b class="ok">on</b></span>
  </footer>

  {#if calibrating}
    <CalibrationOverlay
      camera_id={calibrating}
      onclose={() => {
        calibrating = null;
        refresh();
      }}
    />
  {/if}
</div>
{/if}

<style>
  .app {
    height: 100vh;
    display: grid;
    grid-template-rows: 54px 1fr 30px;
    grid-template-columns: 184px 1fr;
    grid-template-areas: "top top" "rail content" "status status";
  }

  /* top bar */
  .topbar {
    grid-area: top;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 18px;
    background: var(--color-surface-1);
    border-bottom: 1px solid var(--color-border);
    box-shadow: var(--sh-1);
    z-index: 3;
  }
  .brand { display: flex; align-items: center; gap: 11px; }
  .mark {
    width: 32px; height: 32px; border-radius: 8px;
    background: var(--color-accent);
    display: grid; place-items: center;
  }
  .mark svg { width: 18px; height: 18px; }
  .wordmark b { font-size: 15px; font-weight: 700; }
  .wordmark span { color: var(--color-muted); font-size: 12px; }

  .pills { display: flex; align-items: center; gap: 8px; margin-left: 6px; }
  .pill {
    display: inline-flex; align-items: center; gap: 7px; height: 28px; padding: 0 12px;
    background: var(--color-surface-2); border: 1px solid var(--color-border);
    border-radius: 100px; font-size: 12.5px; color: var(--color-muted);
  }
  .pill .num { color: var(--color-text); font-weight: 600; font-variant-numeric: tabular-nums; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-dim); }
  .dot.on { background: var(--color-ok); }
  .dot.off { background: var(--color-critical); }

  .topbar .spacer { flex: 1; }
  .op { display: flex; align-items: center; gap: 10px; padding-left: 14px; border-left: 1px solid var(--color-border); }
  .ava {
    width: 32px; height: 32px; border-radius: 50%;
    background: var(--color-surface-3); color: var(--color-accent-dim);
    border: 1px solid var(--color-border-2);
    display: grid; place-items: center; font-size: 12px; font-weight: 600;
  }
  .who { display: flex; flex-direction: column; line-height: 1.2; }
  .who b { font-size: 13px; font-weight: 600; }
  .who i { font-style: normal; font-size: 11px; color: var(--color-muted); text-transform: capitalize; }
  .who .role-admin { color: var(--color-warn); }
  .who .role-operator { color: var(--color-accent-dim); }
  .who .role-viewer { color: var(--color-ok); }
  .signout {
    background: var(--color-surface-2); border: 1px solid var(--color-border-2); color: var(--color-muted);
    border-radius: 100px; padding: 5px 12px; font-size: 12px;
  }
  .signout:hover { color: var(--color-text); background: var(--color-surface-3); }

  /* rail */
  .rail {
    grid-area: rail;
    background: var(--color-surface-1);
    border-right: 1px solid var(--color-border);
    display: flex; flex-direction: column; padding: 12px; gap: 3px;
  }
  .nav {
    display: flex; align-items: center; gap: 12px; height: 42px; padding: 0 13px;
    border-radius: var(--radius); color: var(--color-muted); background: none; border: 0;
    text-align: left; font-size: 13.5px; font-weight: 550; transition: background 0.15s, color 0.15s;
  }
  .nav svg { width: 19px; height: 19px; flex: none; opacity: 0.9; }
  .nav:hover { background: var(--color-surface-2); color: var(--color-text); }
  .nav.on { background: var(--color-accent-wash); color: var(--color-accent-dim); font-weight: 650; }
  .rail .grow { flex: 1; }
  .rail .tip {
    padding: 12px; border-radius: var(--radius);
    background: color-mix(in srgb, var(--color-accent-wash) 70%, var(--color-surface-2));
    border: 1px solid var(--color-border); font-size: 12px; color: var(--color-muted); line-height: 1.5;
  }
  .rail .tip b { color: var(--color-accent-dim); }

  /* content */
  .content { grid-area: content; overflow: hidden; display: flex; min-height: 0; }
  .content > * { flex: 1; min-width: 0; }
  .scroll { flex: 1; overflow: auto; min-height: 0; }
  .cams { display: flex; flex-direction: column; min-height: 0; }
  .crumb { display: flex; align-items: center; gap: 8px; padding: 8px 16px; font-size: 12.5px; color: var(--color-muted); border-bottom: 1px solid var(--color-border); }
  .crumb button { background: none; border: none; color: var(--color-dim); font-size: 12px; }
  .crumb button:hover { color: var(--color-text); }

  .body { flex: 1; display: grid; grid-template-columns: 1fr 320px; min-height: 0; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 14px; padding: 14px; align-content: start; overflow: auto;
  }
  .cell { cursor: pointer; border-radius: var(--radius-lg); outline: 2px solid transparent; outline-offset: 2px; transition: outline-color 0.15s; }
  .cell.sel { outline-color: var(--color-accent); }
  .cell:focus-visible { outline-color: var(--color-accent); }
  .dock { border-left: 1px solid var(--color-border); background: var(--color-surface-1); overflow: auto; display: flex; flex-direction: column; }
  .sel-bar { display: flex; align-items: center; justify-content: space-between; padding: 11px 16px; border-bottom: 1px solid var(--color-border); font-size: 13px; color: var(--color-accent-dim); }
  .sel-actions { display: flex; gap: 6px; flex-wrap: wrap; }
  .sel-bar button { display: inline-flex; align-items: center; gap: 5px; background: var(--color-surface-2); border: 1px solid var(--color-border-2); color: var(--color-text); border-radius: var(--radius-sm); padding: 5px 10px; font-size: 12.5px; }
  .sel-bar button:hover { background: var(--color-surface-3); }
  .sel-bar button.sahion { background: var(--color-accent-wash); border-color: var(--color-accent); color: var(--color-accent-dim); }
  .conf { display: inline-flex; align-items: center; gap: 4px; }
  .conf button { padding: 3px 9px; }
  .conf .confval { font-size: 12px; color: var(--color-muted); min-width: 58px; text-align: center; font-variant-numeric: tabular-nums; }
  .readonly { margin: 12px 16px; padding: 10px 12px; background: var(--color-surface-2); border: 1px solid var(--color-border); border-radius: var(--radius); font-size: 12.5px; color: var(--color-ok); line-height: 1.4; }
  .hint { grid-column: 1 / -1; display: grid; place-content: center; text-align: center; color: var(--color-dim); padding: 40px; }
  .hint h1 { font-size: 1.15rem; color: var(--color-muted); margin: 0 0 6px; font-weight: 650; }
  .hint p { font-size: 0.9rem; margin: 0; }

  /* status bar */
  .statusbar {
    grid-area: status;
    display: flex; align-items: center; gap: 20px; padding: 0 18px;
    background: var(--color-surface-1); border-top: 1px solid var(--color-border);
    font-size: 12px; color: var(--color-muted);
  }
  .statusbar .s { display: flex; align-items: center; gap: 7px; }
  .statusbar .s b { color: var(--color-text); font-weight: 600; }
  .statusbar .s b.ok { color: var(--color-ok); }
  .statusbar .spacer { flex: 1; }
  .statusbar .dot { width: 7px; height: 7px; }

  /* Narrow windows: collapse the rail to icons and shrink the dock so nothing
     gets clipped by the fixed shell. The camera grid already reflows (auto-fit). */
  @media (max-width: 1024px) {
    .app { grid-template-columns: 60px 1fr; }
    .rail { padding: 12px 8px; }
    .rail .nav { justify-content: center; padding: 0; gap: 0; }
    .rail .nav span, .rail .tip { display: none; }
    .body { grid-template-columns: 1fr 280px; }
  }
  @media (max-width: 760px) {
    .pills { display: none; }
    .body { grid-template-columns: 1fr 240px; }
  }
</style>
