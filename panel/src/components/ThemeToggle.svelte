<script lang="ts">
  // Animated light/dark switch. The theme lives as [data-theme] on <html>;
  // the change is wiped in with a circular reveal from the click point
  // (View Transitions API). Where that API is missing — WebKitGTK and older
  // WKWebView, i.e. Tauri's own webviews — fall back to a palette cross-fade
  // (see --theme-fade in app.css) rather than a hard cut. Reduced motion gets
  // an instant switch either way.
  import { onDestroy } from "svelte";

  type Theme = "dark" | "light";
  const STORE_KEY = "atms_theme";
  const FADE_MS = 260; // keep in sync with --theme-fade in app.css
  const stored = (() => { try { return localStorage.getItem(STORE_KEY) as Theme | null; } catch { return null; } })();
  const initial: Theme = stored || (document.documentElement.getAttribute("data-theme") as Theme) || "dark";
  let theme = $state<Theme>(initial);

  // Tracked live: reading .matches once at init would ignore an OS-level
  // preference change until reload.
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  let reduce = $state(motion.matches);
  const onMotionChange = (e: MediaQueryListEvent) => (reduce = e.matches);
  motion.addEventListener("change", onMotionChange);

  let fadeTimer: ReturnType<typeof setTimeout> | undefined;
  onDestroy(() => {
    motion.removeEventListener("change", onMotionChange);
    clearTimeout(fadeTimer);
  });

  function apply(next: Theme) {
    theme = next;
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem(STORE_KEY, next); } catch { /* private mode / storage disabled */ }
  }

  // Cross-fade every token-driven surface for the length of the switch. Timed
  // rather than transitionend-driven: that event fires per property per element,
  // so there is no single "done" to listen for.
  function fade(next: Theme) {
    const root = document.documentElement;
    root.setAttribute("data-theme-animating", "");
    apply(next);
    clearTimeout(fadeTimer);
    fadeTimer = setTimeout(() => root.removeAttribute("data-theme-animating"), FADE_MS);
  }

  function toggle(e: MouseEvent) {
    const next: Theme = theme === "dark" ? "light" : "dark";
    const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };
    if (reduce) {
      apply(next);
      return;
    }
    if (!doc.startViewTransition) {
      fade(next);
      return;
    }
    const x = e.clientX;
    const y = e.clientY;
    const vt = doc.startViewTransition(() => apply(next));
    vt.ready.then(() => {
      const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
        { duration: 640, easing: "cubic-bezier(.4,0,.2,1)", pseudoElement: "::view-transition-new(root)" },
      );
    });
  }
</script>

<button class="toggle" onclick={toggle} title="Switch theme" aria-label="Switch light/dark theme">
  {#if theme === "dark"}
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
    </svg>
  {:else}
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12.8A8 8 0 1 1 11.2 3a6.2 6.2 0 0 0 9.8 9.8z" />
    </svg>
  {/if}
</button>

<style>
  .toggle {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    border: 1px solid var(--color-border);
    background: var(--color-surface-2);
    color: var(--color-muted);
    display: grid;
    place-items: center;
    transition: background 0.15s, color 0.15s;
  }
  .toggle:hover { color: var(--color-text); background: var(--color-surface-3); }
  .toggle svg { width: 17px; height: 17px; }
</style>
