import type { Snapshot } from './contracts';

export function snapshot(changes: Partial<Snapshot> = {}): Snapshot {
  return {
    schema_version: 1, session_id: 'test-session', instance_id: 'test-instance', command_epoch: 1,
    mode: 'capture', state: 'IDLE', reason: 'Stopped', capture_only: true, calibrating: false,
    frame: { id: 'test-session:1', sequence: 1, captured_at: Date.now() / 1000, age_ms: 5, width: 1024, height: 768, available: true },
    readiness: {
      preview: { ready: true, reason: 'Ready for preview' },
      combat: { ready: false, reason: 'Capture-only input lock' },
      potions: { ready: false, reason: 'Capture-only input lock' },
    },
    calibration: { capture_verified: true },
    player: { kind: 'player', box: { x: 450, y: 350, width: 30, height: 40 }, confidence: 0.95, template: 'nametag:test', tracked: false },
    monsters: [], window: { hwnd: 4, title: 'MapleStory', client: { x: 0, y: 0, width: 1024, height: 768 }, focused: false, dpi: 96 },
    width: 1024, height: 768, bindings: { attack: 'z', jump: 'space' },
    required_probes: ['left', 'right', 'attack', 'jump', 'skill'], optional_probes: ['up', 'down', 'hp_potion', 'mp_potion'], probes: {}, active_probe: null,
    autopotter: { enabled: false, preview_only: true, reason: 'Stopped', settings: { hp_threshold: 50, mp_threshold: 30, cooldown: 1.5 }, calibrated: ['hp', 'mp'], readings: {} },
    stop: null, alarm: { active: false }, restart_available: true, shutdown_available: true, history: [],
    catalog: { species: 12, frames: 120, names: ['Snail'], active_map: 'Subway' },
    ...changes,
  };
}

export function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
