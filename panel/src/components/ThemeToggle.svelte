<script lang="ts">
  // Animated light/dark switch. The theme lives as [data-theme] on <html>;
  // the change is wiped in with a circular reveal from the click point
  // (View Transitions API), falling back to an instant switch where unsupported
  // or when the user prefers reduced motion.
  type Theme = "dark" | "light";
  const initial = (document.documentElement.getAttribute("data-theme") as Theme) || "dark";
  let theme = $state<Theme>(initial);
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  function apply(next: Theme) {
    theme = next;
    document.documentElement.setAttribute("data-theme", next);
  }

  function toggle(e: MouseEvent) {
    const next: Theme = theme === "dark" ? "light" : "dark";
    const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };
    if (reduce || !doc.startViewTransition) {
      apply(next);
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
