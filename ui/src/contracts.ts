// Version 1 of the local Python engine contract. Native-pixel coordinates throughout.
export interface Rect { x: number; y: number; width: number; height: number }
export interface Detection {
  kind: string; box: Rect; confidence: number; template: string; tracked: boolean;
}
export interface Frame {
  id: string | null; source_id: string; sequence: number | null; captured_at: number | null;
  age_ms: number | null; width: number; height: number; available: boolean;
}
export interface Gate { ready: boolean; reason: string }
export interface Probe {
  confirmed: boolean; status?: string; reason?: string;
  [key: string]: unknown;
}
export interface ActiveProbe {
  id: number; generation: number; action: string; phase: string; instruction: string;
}
export interface StopRecord {
  id: string; code: string; severity: string; message: string; time: number;
  clip_path: string | null; acknowledged: boolean; encoding_complete: boolean;
}
export interface PotionStatus {
  enabled: boolean; preview_only: boolean; reason: string; input_sent?: boolean;
  settings: { hp_threshold: number; mp_threshold: number; cooldown: number };
  calibrated: string[];
  readings: Partial<Record<'hp' | 'mp', { percent: number | null; confidence: number; reason: string }>>;
}
export interface Residual { p50: number; p95: number; max: number }
export interface WalkCalibration {
  active: boolean; pairs: number; rejected: number;
  saved: { residual_px: Record<'x' | 'y', Residual>; pairs: number; captured_at: number } | null;
}
// Read-only position on a taught area. A platform is a spatial match, never proof of contact.
export interface LivePosition {
  area_id?: string; area_name?: string; kind: string; surface_id?: string | null;
  feet?: [number, number] | null; reason: string; map?: string; canvas?: Rect | null;
  marker?: [number, number] | null; calibrated?: boolean; stale?: boolean;
  calibration?: WalkCalibration; input_sent: false;
}
export interface WindowInfo { hwnd: number; title: string; client: Rect; focused: boolean; dpi: number }
export interface Snapshot {
  schema_version: 1; session_id: string; instance_id: string; command_epoch: number;
  mode: string; state: string; reason: string; capture_only: boolean; calibrating: boolean;
  frame: Frame; preview_frame?: Frame; readiness: { preview: Gate; combat: Gate; potions: Gate };
  calibration: { capture_verified?: boolean; controls_verified?: boolean; crop?: Rect };
  player: Detection | null; monsters?: Detection[]; target?: Detection | null;
  focused?: boolean; window?: WindowInfo | null; width?: number; height?: number;
  fps?: number; latency_ms?: number; features?: boolean; last_action?: string;
  bindings: Record<string, string | number>; required_probes: string[]; optional_probes: string[];
  probes: Record<string, Probe>; active_probe: ActiveProbe | null;
  autopotter: PotionStatus; stop: StopRecord | null;
  alarm: { active: boolean; incident_id?: string };
  restart_available: boolean; shutdown_available: boolean; recording?: boolean;
  catalog?: { species?: number; frames?: number; names?: string[]; active_map?: string;
    active_variants?: number; map_filter_error?: string; map_filter_held?: boolean };
  failures?: string[]; history: { time: number; reason: string }[];
  stage_timing?: Record<string, number>; encoder?: Record<string, unknown>;
  recorder?: Record<string, unknown>; action_outcome?: Record<string, unknown>;
  area_editing?: boolean; position?: LivePosition | null;
}
export interface CommandEnvelope {
  schema_version: 1; session_id: string; command_id: string; command_epoch: number;
  issued_at: number; expected_frame_id: string | null; name: string;
  payload: Record<string, unknown>;
}
export interface FrozenFrame { id: string; width: number; height: number }
export interface Selection extends Rect { id: string }

export interface AreaPoint { x: number; y: number }
export interface AreaView {
  id: string; name: string; width: number; height: number;
  origin: AreaPoint; scale: number; image: string;
  minimap?: { canvas: Rect; dot: AreaPoint | null } | null;
}
export interface AreaSegment { id: string; start: AreaPoint; end: AreaPoint }
export interface AreaZone { id: string; kind: 'avoid' | 'portal'; rect: Rect }
export interface AreaLink {
  id: string; from: string; to: string; kind: 'walk' | 'jump' | 'climb' | 'drop';
}
export interface AreaProfile {
  schema_version: 1 | 2; id: string; revision: number; name: string; boundary: Rect;
  views: AreaView[]; zones: AreaZone[]; platforms: AreaSegment[]; ropes: AreaSegment[];
  links: AreaLink[]; minimap_calibration?: unknown;
}
