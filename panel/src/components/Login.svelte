<script lang="ts">
  import { login, type Me } from "../lib/gateway";

  let { onauth }: { onauth: (me: Me) => void } = $props();

  let username = $state("");
  let password = $state("");
  let error = $state("");
  let busy = $state(false);

  async function submit(e: Event) {
    e.preventDefault();
    error = "";
    busy = true;
    try {
      onauth(await login(username, password));
    } catch (err) {
      error = err instanceof Error ? err.message : "login failed";
    } finally {
      busy = false;
    }
  }
</script>

<div class="scrim">
  <form class="card" onsubmit={submit}>
    <h1>ATMS Panel</h1>
    <p class="sub">Sign in to continue</p>
    <label>
      <span>Operator</span>
      <input bind:value={username} autocomplete="username" placeholder="username" required />
    </label>
    <label>
      <span>Password</span>
      <input bind:value={password} type="password" autocomplete="current-password" placeholder="password" required />
    </label>
    {#if error}<p class="err">{error}</p>{/if}
    <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
  </form>
</div>

<style>
  .scrim { position: fixed; inset: 0; display: grid; place-items: center; background: var(--color-bg); z-index: 100; }
  .card {
    width: 320px; display: flex; flex-direction: column; gap: 12px;
    background: var(--color-surface-1); border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: 28px;
    box-shadow: var(--sh-2);
  }
  h1 { margin: 0; font-size: 1.2rem; color: var(--color-text); }
  .sub { margin: 0 0 6px; font-size: 0.82rem; color: var(--color-muted); }
  label { display: flex; flex-direction: column; gap: 4px; font-size: 0.72rem; color: var(--color-muted); }
  input {
    background: var(--color-surface-2); border: 1px solid var(--color-border-2); border-radius: var(--radius-sm); padding: 8px 10px;
    color: var(--color-text); font-size: 0.9rem;
  }
  input:focus { outline: none; border-color: var(--color-accent); }
  .err { margin: 0; color: var(--color-critical); font-size: 0.78rem; }
  button {
    margin-top: 6px; background: var(--color-accent); border: 1px solid var(--color-accent); color: #fff;
    border-radius: var(--radius-sm); padding: 9px; cursor: pointer; font-size: 0.85rem; font-weight: 600;
  }
  button:hover:not(:disabled) { background: var(--color-accent-dim); }
  button:disabled { opacity: 0.6; cursor: default; }
</style>
