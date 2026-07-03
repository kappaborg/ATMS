export interface Detection {
  track_id: number;
  label: string;
  confidence: number;
  bbox: [number, number, number, number];
  speed_kmh: number | null;
  approach: string | null;
}

export interface ApproachStat {
  vehicles: number;
  avg_speed_kmh: number;
}

export interface Decision {
  phase: string;
  active_direction: string;
  priority: string;
  confidence: number;
  reason: string;
}

export interface Counts {
  vehicles: number;
  pedestrians: number;
}

export interface FrameEvent {
  type: "frame";
  camera_id: string;
  frame: number;
  ts: number;
  pipeline_latency_ms: number;
  fps: number;
  counts: Counts;
  detections: Detection[];
  approaches: { ns: ApproachStat; ew: ApproachStat };
  calibrated: boolean;
  decision: Decision;
}

export interface CameraInfo {
  camera_id: string;
  source: string;
  status: string;
  error: string | null;
  fps: number;
}
