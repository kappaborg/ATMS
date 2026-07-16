/**
 * Display names for junctions and cameras.
 *
 * The operator names a junction once (city + name); each camera says which arm
 * of it it watches. Names are composed from those parts rather than typed per
 * camera, so two cameras on one junction can never disagree about where they
 * are, and renaming a site updates every camera on it.
 *
 * Everything degrades to the raw id: cameras added before naming existed, and
 * junctions nobody has named yet, still render something an operator can act on.
 */
import type { Approach, CameraInfo, IntersectionInfo } from "./types";

type Named = { intersection_id: string; name: string | null; city: string | null };

export const APPROACHES: Approach[] = ["north", "south", "east", "west"];

export const APPROACH_LABEL: Record<Approach, string> = {
  north: "North",
  south: "South",
  east: "East",
  west: "West",
};

/** Has anyone actually named this junction? */
export function isNamed(j: Named | undefined): boolean {
  return Boolean(j && (j.name || j.city));
}

/** "Sarajevo · Marijin Dvor" — or "Junction 1" while unnamed. */
export function junctionLabel(j: Named | undefined): string {
  if (!j) return "Junction";
  const parts = [j.city, j.name].filter(Boolean);
  return parts.length ? parts.join(" · ") : `Junction ${j.intersection_id}`;
}

/** "Sarajevo · Marijin Dvor · North" — what an operator should see instead of
 * a raw id. Falls back to the id when the junction is unnamed or the camera has
 * no approach set. */
export function cameraLabel(cam: CameraInfo, junctions: IntersectionInfo[]): string {
  const j = junctions.find((i) => i.intersection_id === cam.intersection_id);
  const dir = cam.approach ? APPROACH_LABEL[cam.approach] : null;
  if (!isNamed(j)) return cam.camera_id;
  return dir ? `${junctionLabel(j)} · ${dir}` : `${junctionLabel(j)} · ${cam.camera_id}`;
}

/** The short form for tight spots (tile corners, map nodes): just the approach
 * where we have one, else the id. */
export function cameraShortLabel(cam: CameraInfo): string {
  return cam.approach ? APPROACH_LABEL[cam.approach] : cam.camera_id;
}
