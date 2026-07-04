import type { CameraInfo, FrameEvent, IntersectionInfo, Corridor } from "./types";

const BASE = import.meta.env.VITE_GATEWAY ?? "http://127.0.0.1:8090";
const WS_BASE = BASE.replace(/^http/, "ws");

// Session token: from a login (preferred) or a build-time VITE_GATEWAY_TOKEN.
// Persisted so a reopened app stays signed in until the token expires.
let TOKEN: string =
  localStorage.getItem("atms_token") ??
  ((import.meta.env.VITE_GATEWAY_TOKEN as string | undefined) ?? "");

function setToken(t: string) {
  TOKEN = t;
  if (t) localStorage.setItem("atms_token", t);
  else localStorage.removeItem("atms_token");
}

// REST auth header (empty when no token configured).
const authHeaders = (): Record<string, string> =>
  TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
// WebSocket can't set headers in the browser — pass the token as a query param.
const wsAuth = (): string => (TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : "");

export interface Me {
  username: string;
  role: "viewer" | "operator" | "admin";
}

/** True when the gateway requires authentication. */
export async function authRequired(): Promise<boolean> {
  const r = await fetch(`${BASE}/health`);
  if (!r.ok) return false;
  return Boolean((await r.json()).auth_enabled);
}

/** Validate the stored token; returns the principal or null. */
export async function getMe(): Promise<Me | null> {
  if (!TOKEN) return null;
  const r = await fetch(`${BASE}/auth/me`, { headers: authHeaders() });
  return r.ok ? r.json() : null;
}

export async function login(username: string, password: string): Promise<Me> {
  const r = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) throw new Error(r.status === 401 ? "Invalid username or password" : `login ${r.status}`);
  const data = await r.json();
  setToken(data.token);
  return { username: data.username, role: data.role };
}

export function logout() {
  setToken("");
}

// --- REST ---
export async function listCameras(): Promise<CameraInfo[]> {
  const r = await fetch(`${BASE}/cameras`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`listCameras ${r.status}`);
  return r.json();
}

export async function listIntersections(): Promise<IntersectionInfo[]> {
  const r = await fetch(`${BASE}/intersections`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`listIntersections ${r.status}`);
  return r.json();
}

export async function listCorridors(): Promise<Corridor[]> {
  const r = await fetch(`${BASE}/corridors`, { headers: authHeaders() });
  if (!r.ok) return [];
  return r.json();
}

export async function addCorridor(payload: unknown): Promise<Corridor> {
  const r = await fetch(`${BASE}/corridors`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `addCorridor ${r.status}`);
  return r.json();
}

export async function removeCorridor(id: string): Promise<void> {
  await fetch(`${BASE}/corridors/${encodeURIComponent(id)}`, { method: "DELETE", headers: authHeaders() });
}

export async function addCamera(camera_id: string, source: string, loop_file = true) {
  const r = await fetch(`${BASE}/cameras`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ camera_id, source, loop_file }),
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? `addCamera ${r.status}`);
  return r.json();
}

export async function removeCamera(camera_id: string) {
  const r = await fetch(`${BASE}/cameras/${encodeURIComponent(camera_id)}`, { method: "DELETE", headers: authHeaders() });
  if (!r.ok) throw new Error(`removeCamera ${r.status}`);
  return r.json();
}

export interface ScenePayload {
  calibration?: { image_points: [number, number][]; world_points_m: [number, number][] };
  zones?: Record<string, [number, number][]>;
  zone_directions?: Record<string, "ns" | "ew">;
  stop_lines?: { approach: "ns" | "ew"; points: [number, number][] }[];
}

export interface SceneInfo {
  calibrated: boolean;
  reprojection_error_m: number | null;
  zones: string[];
  zone_directions: Record<string, string>;
}

export async function setScene(camera_id: string, payload: ScenePayload): Promise<SceneInfo> {
  const r = await fetch(`${BASE}/cameras/${encodeURIComponent(camera_id)}/scene`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `setScene ${r.status}`);
  return r.json();
}

/**
 * Grab a single frozen frame from a camera's video stream (for calibration).
 * Resolves with an object URL; caller revokes it when done.
 */
export function snapshotFrame(camera_id: string, timeoutMs = 5000): Promise<string> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`${WS_BASE}/ws/video/${encodeURIComponent(camera_id)}${wsAuth()}`);
    ws.binaryType = "blob";
    const timer = setTimeout(() => {
      ws.close();
      reject(new Error("snapshot timed out"));
    }, timeoutMs);
    ws.onmessage = (ev) => {
      clearTimeout(timer);
      ws.close();
      resolve(URL.createObjectURL(ev.data as Blob));
    };
    ws.onerror = () => {
      clearTimeout(timer);
      reject(new Error("snapshot failed"));
    };
  });
}

export interface VideoDevice {
  index: number;
  width: number;
  height: number;
}

export async function listDevices(): Promise<VideoDevice[]> {
  const r = await fetch(`${BASE}/devices`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`listDevices ${r.status}`);
  return r.json();
}

/** Fetch the camera's session report and trigger a CSV download. */
export async function downloadReport(camera_id: string): Promise<void> {
  const r = await fetch(
    `${BASE}/cameras/${encodeURIComponent(camera_id)}/report?format=csv`,
    { headers: authHeaders() },
  );
  if (!r.ok) throw new Error(`report ${r.status}`);
  const blob = new Blob([await r.text()], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `atms-report-${camera_id}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Emergency-vehicle preemption: force `direction` green, or clear it. */
export async function setPreemption(
  camera_id: string,
  direction: "north_south" | "east_west",
  active: boolean,
): Promise<void> {
  const r = await fetch(`${BASE}/cameras/${encodeURIComponent(camera_id)}/preempt`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ direction, active }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `preempt ${r.status}`);
}

export interface HistoryTotals {
  vehicles: number;
  co2_kg: number;
  saved_kg: number;
  incidents: number;
}

/** Persisted historical totals for a camera over the last `hours`. */
export async function getHistory(camera_id: string, hours: number): Promise<HistoryTotals | null> {
  const r = await fetch(
    `${BASE}/history?hours=${hours}&camera_id=${encodeURIComponent(camera_id)}`,
    { headers: authHeaders() },
  );
  if (!r.ok) return null;
  return (await r.json()).totals;
}

export async function health(): Promise<boolean> {
  try {
    const r = await fetch(`${BASE}/health`);
    return r.ok;
  } catch {
    return false;
  }
}

/**
 * Auto-reconnecting data stream. Calls onEvent for every frame event and
 * onStatus when the connection state changes.
 */
export function connectData(
  onEvent: (e: FrameEvent) => void,
  onStatus?: (connected: boolean) => void,
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let retry = 500;

  const open = () => {
    if (closed) return;
    ws = new WebSocket(`${WS_BASE}/ws/data${wsAuth()}`);
    ws.onopen = () => {
      retry = 500;
      onStatus?.(true);
    };
    ws.onmessage = (ev) => {
      try {
        onEvent(JSON.parse(ev.data) as FrameEvent);
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      onStatus?.(false);
      if (!closed) setTimeout(open, (retry = Math.min(retry * 2, 5000)));
    };
    ws.onerror = () => ws?.close();
  };
  open();

  return () => {
    closed = true;
    ws?.close();
  };
}

/**
 * Video stream for one camera. Receives JPEG blobs and hands back object URLs
 * to assign to an <img>. Revokes the previous URL to avoid leaks.
 */
export function connectVideo(
  camera_id: string,
  onFrame: (url: string) => void,
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let prevUrl: string | null = null;
  let retry = 500;

  const open = () => {
    if (closed) return;
    ws = new WebSocket(`${WS_BASE}/ws/video/${encodeURIComponent(camera_id)}${wsAuth()}`);
    ws.binaryType = "blob";
    ws.onopen = () => (retry = 500);
    ws.onmessage = (ev) => {
      const url = URL.createObjectURL(ev.data as Blob);
      onFrame(url);
      if (prevUrl) URL.revokeObjectURL(prevUrl);
      prevUrl = url;
    };
    ws.onclose = () => {
      if (!closed) setTimeout(open, (retry = Math.min(retry * 2, 5000)));
    };
    ws.onerror = () => ws?.close();
  };
  open();

  return () => {
    closed = true;
    ws?.close();
    if (prevUrl) URL.revokeObjectURL(prevUrl);
  };
}
