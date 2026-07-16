<script lang="ts">
  import type { Corridor, IntersectionInfo } from "../lib/types";
  import { addCorridor, removeCorridor } from "../lib/gateway";
  import TimeSpaceDiagram from "./TimeSpaceDiagram.svelte";
  import Icon from "./Icon.svelte";

  let {
    corridors,
    intersections,
    canOperate = false,
    onchange,
  }: {
    corridors: Corridor[];
    intersections: IntersectionInfo[];
    canOperate?: boolean;
    onchange: () => void;
  } = $props();

  let show = $state(false);
  let cid = $state("");
  let direction = $state<"north_south" | "east_west">("north_south");
  let speed = $state(50);
  let cycle = $state(60);
  let green = $state(27);
  let stops = $state<{ intersection_id: string; distance_m: number }[]>([
    { intersection_id: "", distance_m: 0 },
    { intersection_id: "", distance_m: 400 },
  ]);
  let error = $state("");

  function addStop() {
    stops = [...stops, { intersection_id: "", distance_m: 400 }];
  }
  function removeStop(i: number) {
    stops = stops.filter((_, j) => j !== i);
  }

  async function submit() {
    error = "";
    const chosen = stops.filter((s) => s.intersection_id);
    if (!cid || chosen.length < 2) {
      error = "Need a name and at least 2 intersections.";
      return;
    }
    try {
      await addCorridor({
        corridor_id: cid,
        direction,
        design_speed_kmh: speed,
        cycle_s: cycle,
        green_s: green,
        stops: chosen.map((s) => ({ intersection_id: s.intersection_id, distance_m: Number(s.distance_m) })),
      });
      show = false;
      cid = "";
      onchange();
    } catch (e) {
      error = e instanceof Error ? e.message : "failed";
    }
  }

  async function del(id: string) {
    await removeCorridor(id);
    onchange();
  }
</script>

<div class="corridors">
  <div class="head">
    <h2>Green-wave corridors</h2>
    {#if canOperate}
      <button onclick={() => (show = !show)}>{show ? "Cancel" : "+ New corridor"}</button>
    {/if}
  </div>

  {#if show}
    <div class="form">
      <div class="row">
        <input placeholder="corridor name" bind:value={cid} />
        <select bind:value={direction}>
          <option value="north_south">N–S</option>
          <option value="east_west">E–W</option>
        </select>
      </div>
      <div class="row">
        <label>Speed<input type="number" bind:value={speed} /></label>
        <label>Cycle<input type="number" bind:value={cycle} /></label>
        <label>Green<input type="number" bind:value={green} /></label>
      </div>
      <div class="stops">
        <span class="hint">Intersections in order (distance from previous, m):</span>
        {#each stops as s, i}
          <div class="strow">
            <select bind:value={s.intersection_id}>
              <option value="">— pick —</option>
              {#each intersections as it}
                <option value={it.intersection_id}>Int {it.intersection_id}</option>
              {/each}
            </select>
            <input type="number" bind:value={s.distance_m} placeholder="m" />
            {#if stops.length > 2}<button class="x" onclick={() => removeStop(i)} aria-label="remove stop"><Icon name="close" size={13} /></button>{/if}
          </div>
        {/each}
        <button class="addstop" onclick={addStop}>+ stop</button>
      </div>
      {#if error}<p class="err">{error}</p>{/if}
      <button class="apply" onclick={submit}>Create green wave</button>
    </div>
  {/if}

  {#each corridors as c (c.corridor_id)}
    <div class="corr">
      <div class="chead">
        <b>{c.corridor_id}</b>
        {#if canOperate}<button class="del" onclick={() => del(c.corridor_id)}>remove</button>{/if}
      </div>
      <TimeSpaceDiagram corridor={c} />
    </div>
  {:else}
    {#if !show}<p class="none">No corridors. Coordinate a route of intersections into a green wave.</p>{/if}
  {/each}
</div>

<style>
  .corridors { padding: 0 16px 20px; }
  .head { display: flex; align-items: center; justify-content: space-between; margin: 8px 0; }
  h2 { font-size: 0.9rem; color: var(--color-accent-dim); margin: 0; }
  .strow .x { display: inline-flex; align-items: center; }
  .head button { background: var(--color-surface-2); border: 1px solid var(--color-border-2); color: var(--color-text); border-radius: var(--radius-sm); padding: 4px 10px; cursor: pointer; font-size: 0.74rem; }
  .head button:hover { background: var(--color-surface-3); }
  .form { background: var(--color-surface-1); border: 1px solid var(--color-border); border-radius: var(--radius); padding: 12px; margin-bottom: 12px; display: flex; flex-direction: column; gap: 8px; }
  .row { display: flex; gap: 8px; }
  .row input, .row select, .strow input, .strow select { background: var(--color-surface-2); border: 1px solid var(--color-border-2); border-radius: var(--radius-sm); padding: 5px 8px; color: var(--color-text); font-size: 0.8rem; }
  .row label { display: flex; flex-direction: column; font-size: 0.66rem; color: var(--color-muted); gap: 2px; flex: 1; }
  .row label input { width: 100%; }
  .stops { display: flex; flex-direction: column; gap: 6px; }
  .hint { font-size: 0.68rem; color: var(--color-muted); }
  .strow { display: flex; gap: 6px; align-items: center; }
  .strow .x { background: none; border: none; color: var(--color-critical); cursor: pointer; }
  .addstop { align-self: flex-start; background: none; border: 1px dashed var(--color-border-2); color: var(--color-muted); border-radius: var(--radius-sm); padding: 3px 8px; cursor: pointer; font-size: 0.72rem; }
  .apply { background: var(--color-accent); border: 1px solid var(--color-accent); color: #fff; border-radius: var(--radius-sm); padding: 7px; cursor: pointer; font-size: 0.82rem; font-weight: 600; }
  .apply:hover { background: var(--color-accent-dim); }
  .err { color: var(--color-critical); font-size: 0.74rem; margin: 0; }
  .corr { background: var(--color-surface-1); border: 1px solid var(--color-border); border-radius: var(--radius); padding: 10px; margin-bottom: 10px; }
  .chead { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 0.85rem; color: var(--color-text); }
  .del { background: none; border: 1px solid var(--color-border-2); color: var(--color-critical); border-radius: var(--radius-sm); padding: 2px 8px; cursor: pointer; font-size: 0.7rem; }
  .none { color: var(--color-dim); font-size: 0.78rem; }
</style>
