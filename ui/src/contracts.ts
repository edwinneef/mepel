import type { PotionEvidence } from './potionEvidence';

// Version 1 of the local Python engine contract. Native-pixel coordinates throughout.
export interface Rect { x: number; y: number; width: number; height: number }
export interface Detection {
  kind: string; box: Rect; confidence: number; template: string; tracked: boolean;
  track_id?: string | null;
}
export interface EnemyTrack {
  track_id: string; enemy_type: string;
  state: 'visible' | 'partially_occluded' | 'occluded' | 'lost';
  predicted_position: [number, number]; ground_position: [number, number];
  visible_bounds: Rect | null; confidence: number; uncertainty: [number, number];
  last_seen: number; observed: boolean;
}
export interface PlayerTracking {
  state: 'confirmed' | 'tracked' | 'coasting' | 'lost';
  predicted: Rect | null; observed: Rect | null; search: Rect | null;
  /** Grid cell outside the search window where monsters were also searched this frame. */
  enemy_cell?: Rect | null;
  confidence: number; identity: string | null; since_confirmed: number | null;
}
export interface Frame {
  id: string | null; source_id: string; sequence: number | null; captured_at: number | null;
  age_ms: number | null; width: number; height: number; available: boolean;
}
export interface Gate { ready: boolean; reason: string }
export interface CombatEvidence {
  session_id: string; run: number; activity: string; started_at: number;
  stop_reason: string | null; hit_confirmed: null;
  events: { time: number; kind: string; detail: string; before?: number; after?: number;
    observation: { frame_id?: string; captured_at?: number;
      same_platform_targets?: { distance_px: number; direction: string; template?: string }[] } }[];
}
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
  /** Pairs collected while you walk an uncalibrated map with input idle. */
  passive?: { pairs: number; rejected: number; reason: string };
  saved: { residual_px: Record<'x' | 'y', Residual>; pairs: number; captured_at: number } | null;
}
export interface TaughtGeometry {
  platforms: AreaSegment[]; ropes: AreaSegment[]; links: AreaLink[]; boundary: Rect | null;
  problems?: { home: string | null; unreachable: string[]; stranded: string[] };
  aliases?: Record<string, string>;
}
// Read-only position on a taught area. A platform is a spatial match, never proof of contact.
export interface LivePosition {
  area_id?: string; area_name?: string; kind: string; surface_id?: string | null;
  feet?: [number, number] | null; reason: string; map?: string; canvas?: Rect | null;
  marker?: [number, number] | null; calibrated?: boolean; stale?: boolean;
  captured_at?: number;
  projection?: { x: number; y: number; scale: number; revision: number } | null;
  calibration?: WalkCalibration; input_sent: false;
  map_alignment?: { mode: 'automatic'; state: 'aligning' | 'uncertain' | 'ready';
    uncertainty_px: number; precision_verified: boolean; observed_surface?: string | null;
    reason: string } | null;
  movement_learning?: { state: string; samples: number; observed_speed_px_s: number | null;
    parameters: Record<string, number>; unidentified: string[]; reason: string;
    input_sent: false } | null;
  teaching?: TeachingSession;
  provisional?: boolean;
  supplement?: { available: boolean; enabled: boolean; reason: string; platform: AreaSegment | null };
}
export interface TeachingSession {
  phase: 'calibrating' | 'recording' | 'review' | 'interrupted' | 'conflict' | null;
  geometry: TaughtGeometry | null; samples: number;
  draft?: { id: string; revision: number; saved_at: number | null; saved: boolean; pending?: boolean; error: string | null };
  map_revision?: number; map_receipt?: { revision: number; saved_at: number } | null;
  health?: { checks: number; misses: number; last_reason: string | null };
  references?: AreaView[]; evidence?: string[]; geometry_source?: 'draft' | 'active_map';
}
export interface WindowInfo { hwnd: number; title: string; client: Rect; focused: boolean; dpi: number }
export interface LiveDetections {
  enemy_tracks?: EnemyTrack[];
  player_tracking?: PlayerTracking | null;
  frame: Frame; player: Detection | null; monsters?: Detection[] | null;
  target?: Detection | null; position?: LivePosition | null;
  display?: boolean;
  terrain?: LivePosition & { alignment: { valid: boolean; [key: string]: unknown } } | null;
}
export interface Snapshot {
  pose_collection?: { enabled: boolean; identity: string; outfit: string; identities: string[]; saved: number; duplicates: number; rejected: number; pending: number; limit: number; reason: string };
  enemy_tracks?: EnemyTrack[];
  player_tracking?: PlayerTracking | null;
  schema_version: 1; session_id: string; instance_id: string; command_epoch: number;
  mode: string; state: string; reason: string; capture_only: boolean; calibrating: boolean;
  frame: Frame; preview_frame?: Frame; readiness: { preview: Gate; combat: Gate; potions: Gate; [activity: string]: Gate };
  attack_setup?: { minimum_px: number; maximum_px: number; measured: boolean; reason: string };
  player_threshold?: number;
  combat_evidence?: CombatEvidence | null;
  potion_evidence?: PotionEvidence | null;
  live_detections?: LiveDetections | null;
  health?: { camera: boolean; recognition: boolean; position: boolean; reason: string; warning?: string | null };
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
  area_editing?: boolean; position?: LivePosition | null; sustain?: string[];
  navigation?: NavigationStatus;
}
export interface CommandEnvelope {
  schema_version: 1; session_id: string; command_id: string; command_epoch: number;
  issued_at: number; expected_frame_id: string | null; name: string;
  payload: Record<string, unknown>;
}
export interface FrozenFrame { id: string; width: number; height: number }
export interface Selection extends Rect { id: string }

export interface NavigationRoute {
  area_id: string; revision: number; fingerprint: string; origin: string; target: string;
  edges: { id: string; source: string; target: string; kind: string;
    launch: [number, number]; landing: [number, number]; evidence: string }[];
}
export interface NavigationStatus {
  stage: string; reason: string; active: boolean; ready: boolean; blocker: string | null;
  route: NavigationRoute | null; edge_index?: number; completed?: number;
  retries?: number; replans?: number;
  map: { area_id: string; revision: number; home: string; usable_edges: number;
    nodes: { id: string; name: string; kind: string; excluded: boolean }[];
    disabled_edges: Record<string, string> } | null;
}

export interface AreaPoint { x: number; y: number }
export interface AreaView {
  id: string; name: string; width: number; height: number;
  origin: AreaPoint; scale: number; image: string;
  minimap?: { canvas: Rect; dot: AreaPoint | null } | null;
}
export interface ViewAlignment {
  aligned: boolean; view_id: string | null; origin: AreaPoint | null; scale: number | null;
  agree: number; patches: number; reason: string;
}
export interface AreaSegment { id: string; start: AreaPoint; end: AreaPoint; name?: string }
export interface AreaZone { id: string; kind: 'avoid' | 'portal'; rect: Rect }
export interface AreaLink {
  id: string; from: string; to: string; kind: 'walk' | 'jump' | 'climb' | 'drop';
}
export interface AreaProfile {
  schema_version: 1 | 2; id: string; revision: number; name: string; boundary: Rect;
  views: AreaView[]; zones: AreaZone[]; platforms: AreaSegment[]; ropes: AreaSegment[];
  links: AreaLink[]; minimap_calibration?: unknown;
}
