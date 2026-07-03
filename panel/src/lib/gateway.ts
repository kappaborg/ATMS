import type { CameraInfo, FrameEvent } from "./types";

const BASE = import.meta.env.VITE_GATEWAY ?? "http://127.0.0.1:8090";
const WS_BASE = BASE.replace(/^http/, "ws");
const TOKEN = (import.meta.env.VITE_GATEWAY_TOKEN as string | undefined) ?? "";

// REST auth header (empty when no token configured).
const authHeaders = (): Record<string, string> =>
  TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
// WebSocket can't set headers in the browser — pass the token as a query param.
const wsAuth = (): string => (TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : "");

// --- REST ---
export async function listCameras(): Promise<CameraInfo[]> {
  const r = await fetch(`${BASE}/cameras`, { headers: authHeaders() });
  if (!r.ok) throw new Error(`listCameras ${r.status}`);
  return r.json();
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
