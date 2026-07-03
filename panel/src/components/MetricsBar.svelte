<script lang="ts">
  import type { FrameEvent } from "../lib/types";
  let {
    events,
    connected,
    dataHz,
  }: { events: Record<string, FrameEvent>; connected: boolean; dataHz: number } = $props();

  const totals = $derived.by(() => {
    let veh = 0, ped = 0, lat = 0, n = 0;
    for (const e of Object.values(events)) {
      veh += e.counts.vehicles;
      ped += e.counts.pedestrians;
      lat += e.pipeline_latency_ms;
      n++;
    }
    return { veh, ped, lat: n ? lat / n : 0, cams: n };
  });
</script>

<div class="bar">
  <div class="brand">ATMS <span>Panel</span></div>
  <div class="metrics">
    <div class="m"><b>{totals.cams}</b><span>cameras</span></div>
    <div class="m"><b>{totals.veh}</b><span>vehicles</span></div>
    <div class="m"><b>{totals.ped}</b><span>pedestrians</span></div>
    <div class="m"><b>{totals.lat.toFixed(0)}<i>ms</i></b><span>avg latency</span></div>
    <div class="m"><b>{dataHz.toFixed(0)}<i>/s</i></b><span>data rate</span></div>
  </div>
  <div class="conn" class:on={connected}>
    <span class="dot"></span>{connected ? "connected" : "offline"}
  </div>
</div>

<style>
  .bar { display: flex; align-items: center; gap: 24px; padding: 10px 18px; background: #0d0f14; border-bottom: 1px solid #1e2230; }
  .brand { font-weight: 700; font-size: 1.05rem; color: #fff; }
  .brand span { color: #7fd1ff; font-weight: 400; }
  .metrics { display: flex; gap: 22px; margin-left: auto; }
  .m { display: flex; flex-direction: column; align-items: flex-end; }
  .m b { font-size: 1.05rem; color: #eaf1f8; }
  .m b i { font-size: 0.65rem; color: #8b95a7; font-style: normal; margin-left: 1px; }
  .m span { font-size: 0.65rem; color: #8b95a7; text-transform: uppercase; letter-spacing: 0.04em; }
  .conn { display: flex; align-items: center; gap: 6px; font-size: 0.75rem; color: #e74c3c; }
  .conn.on { color: #2ecc71; }
  .conn .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 6px currentColor; }
</style>
