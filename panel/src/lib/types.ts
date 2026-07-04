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

export interface Emissions {
  total_co2_kg: number;
  idle_co2_kg: number;
  vehicles: number;
  avg_g_per_km: number;
  rate_kg_h: number;
  est_saved_kg: number;
  savings_ratio: number;
}

export interface Decision {
  phase: string;
  active_direction: string;
  priority: string;
  confidence: number;
  reason: string;
  predicted_congestion: { north_south: number; east_west: number; horizon_min: number } | null;
}

export interface SystemDecision {
  intersection_id: string;
  commanded_phase: string | null;
  recommended_phase: string | null;
  priority: string | null;
  confidence: number | null;
  reason: string | null;
  age_s: number | null;
  stale: boolean;
  source: string;
  mode: string | null; // ai_adaptive | fixed_time | all_red_flash | null
  mode_reachable: boolean;
}

export interface Counts {
  vehicles: number;
  pedestrians: number;
}

export interface Incident {
  type: string;
  track_id: number;
  seconds: number;
  label: string;
}

export interface Violation {
  type: "stopped_vehicle" | "speeding" | "wrong_way";
  track_id: number;
  seconds?: number;
  speed_kmh?: number;
  limit_kmh?: number;
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
  incidents: Incident[];
  violations: Violation[];
  emissions: Emissions | null;
  preemption: "north_south" | "east_west" | null;
  transit: { ns: boolean; ew: boolean };
  pedestrian: { present: boolean; clearance_hold: boolean };
  approaches: { ns: ApproachStat; ew: ApproachStat };
  calibrated: boolean;
  decision: Decision;
  intersection_id: string;
  system: SystemDecision | null;
}

export interface CameraInfo {
  camera_id: string;
  source: string;
  kind: "rtsp" | "http" | "usb" | "file";
  live: boolean;
  intersection_id: string;
  status: string;
  error: string | null;
  fps: number;
}

export interface IntersectionInfo {
  intersection_id: string;
  cameras: string[];
  system: SystemDecision | null;
}

export interface Corridor {
  corridor_id: string;
  direction: string;
  design_speed_kmh: number;
  cycle_s: number;
  green_s: number;
  offsets: Record<string, number>;
  bands: { intersection_id: string; distance_m: number; windows: [number, number][] }[];
  trajectory: [number, number][];
  length_m: number;
}
