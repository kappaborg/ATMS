import type { CameraInfo, FrameEvent } from "./types";

const BASE = import.meta.env.VITE_GATEWAY ?? "http://127.0.0.1:8090";
const WS_BASE = BASE.replace(/^http/, "ws");

// --- REST ---
export async function listCameras(): Promise<CameraInfo[]> {
  const r = await fetch(`${BASE}/cameras`);
  if (!r.ok) throw new Error(`listCameras ${r.status}`);
  return r.json();
}

export async function addCamera(camera_id: string, source: string, loop_file = true) {
  const r = await fetch(`${BASE}/cameras`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ camera_id, source, loop_file }),
  });
  if (!r.ok) throw new Error((await r.json()).detail ?? `addCamera ${r.status}`);
  return r.json();
}

export async function removeCamera(camera_id: string) {
  const r = await fetch(`${BASE}/cameras/${encodeURIComponent(camera_id)}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`removeCamera ${r.status}`);
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
    ws = new WebSocket(`${WS_BASE}/ws/data`);
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
    ws = new WebSocket(`${WS_BASE}/ws/video/${encodeURIComponent(camera_id)}`);
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
