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
  .scrim { position: fixed; inset: 0; display: grid; place-items: center; background: #06080c; z-index: 100; }
  .card {
    width: 320px; display: flex; flex-direction: column; gap: 12px;
    background: #0d0f14; border: 1px solid #1e2230; border-radius: 12px; padding: 28px;
  }
  h1 { margin: 0; font-size: 1.2rem; color: #eaf1f8; }
  .sub { margin: 0 0 6px; font-size: 0.82rem; color: #7a8494; }
  label { display: flex; flex-direction: column; gap: 4px; font-size: 0.72rem; color: #8b95a7; }
  input {
    background: #11151d; border: 1px solid #232838; border-radius: 6px; padding: 8px 10px;
    color: #eaf1f8; font-size: 0.9rem;
  }
  input:focus { outline: none; border-color: #2b6ea3; }
  .err { margin: 0; color: #e74c3c; font-size: 0.78rem; }
  button {
    margin-top: 6px; background: #1b3a52; border: 1px solid #2b6ea3; color: #cfe8ff;
    border-radius: 6px; padding: 9px; cursor: pointer; font-size: 0.85rem;
  }
  button:disabled { opacity: 0.6; cursor: default; }
</style>
