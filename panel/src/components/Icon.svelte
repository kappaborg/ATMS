<script lang="ts" module>
  // Single source of truth for the app's line icons. One consistent stroke
  // style everywhere replaces the ad-hoc emoji that were sprinkled through the
  // UI. Each entry is the inner markup of a 24×24, currentColor-stroked svg.
  export type IconName =
    | "signal" | "no-entry" | "speed" | "drift" | "reckless" | "warning"
    | "siren" | "pedestrian" | "bus" | "leaf" | "chart" | "forecast"
    | "download" | "gear" | "close" | "arrow-right" | "swap";

  const P: Record<IconName, string> = {
    // traffic light — ran-red
    signal: '<rect x="8" y="2.5" width="8" height="19" rx="3"/><path d="M8 7.5h8M8 12h8M8 16.5h8"/>',
    // no-entry — wrong way
    "no-entry": '<circle cx="12" cy="12" r="9"/><path d="M7.5 12h9"/>',
    // gauge — speeding
    speed: '<path d="M4 16a8 8 0 0 1 16 0"/><path d="M12 16l4.5-4.5"/><path d="M4 16h1.5M18.5 16H20M12 8V6.5"/>',
    // wind lines — drift
    drift: '<path d="M3 8h10a2.4 2.4 0 1 0-2.4-2.4"/><path d="M3 12h14a2.4 2.4 0 1 1-2.4 2.4"/><path d="M3 16h7"/>',
    // wavy line — reckless / erratic
    reckless: '<path d="M3 12c3-5 5 5 8 0s5-5 8 0"/>',
    // triangle — warning / stopped / uncalibrated
    warning: '<path d="M12 4 21 19H3z"/><path d="M12 10v4"/><circle cx="12" cy="16.6" r=".7" fill="currentColor" stroke="none"/>',
    // siren — emergency
    siren: '<path d="M5.5 20h13"/><path d="M8 20v-5a4 4 0 0 1 8 0v5"/><path d="M12 7V4"/><path d="M17.5 8l1.4-1.4M6.5 8 5.1 6.6"/>',
    // walking figure — pedestrian
    pedestrian: '<circle cx="12" cy="4.4" r="2"/><path d="M12 7v6.5"/><path d="m12 9.5-3 2M12 9.5l3 2"/><path d="m12 13.5-2 6.5M12 13.5l2 6.5"/>',
    // bus — transit priority
    bus: '<rect x="4" y="4" width="16" height="12.5" rx="2.5"/><path d="M4 11.5h16"/><circle cx="8" cy="20" r="1.5"/><circle cx="16" cy="20" r="1.5"/>',
    // leaf — emissions
    leaf: '<path d="M5 19c0-7.5 5.5-13 14-13.5C18.5 13 13 19 5 19z"/><path d="M9 15c1.8-2.2 4-3.6 6.5-4.5"/>',
    // bar chart — history
    chart: '<path d="M4 4v16h16"/><rect x="7.5" y="11" width="3" height="6"/><rect x="13.5" y="7" width="3" height="10"/>',
    // trend line — forecast
    forecast: '<path d="M4 15l5-5 4 3 7-8"/><path d="M16 5h4v4"/>',
    // download — export / report
    download: '<path d="M12 4v11"/><path d="m8 11 4 4 4-4"/><path d="M5 20h14"/>',
    // gear — calibrate
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5 5l2.1 2.1M16.9 16.9 19 19M19 5l-2.1 2.1M7.1 16.9 5 19"/>',
    // close
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    "arrow-right": '<path d="M5 12h13M12 6l6 6-6 6"/>',
    swap: '<path d="M7 8h11l-3-3M17 16H6l3 3"/>',
  };
</script>

<script lang="ts">
  let { name, size = 16, stroke = 1.8, class: cls = "" }: { name: IconName; size?: number; stroke?: number; class?: string } = $props();
</script>

<svg
  class={cls}
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={stroke}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  {@html P[name]}
</svg>
