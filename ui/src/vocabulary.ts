import type { Snapshot } from './contracts';

/* One vocabulary for the dashboard, the in-game widget and the overlays (design 2a).
   Words are chosen once here so every surface says the same thing. */

export type BotState = 'off' | 'starting' | 'running' | 'alarm' | 'disconnected';
export type Tone = 'idle' | 'busy' | 'go' | 'stop';

export const STATE_WORDS: Record<BotState, string> = {
  off: 'Off', starting: 'Starting', running: 'Running', alarm: 'Needs you', disconnected: 'Not connected',
};
export const STATE_TONES: Record<BotState, Tone> = {
  off: 'idle', starting: 'busy', running: 'go', alarm: 'stop', disconnected: 'idle',
};

/** Map the overlay's status code (OFF/STARTING/ON/BLOCKED/DISCONNECTED) and a running batch to a state. */
export function botState(status: string, batchRunning = false): BotState {
  if (status === 'DISCONNECTED') return 'disconnected';
  if (status === 'BLOCKED') return 'alarm';
  if (batchRunning || status === 'ON') return 'running';
  if (status === 'STARTING') return 'starting';
  return 'off';
}

export type Plan = 'loop' | 'platform' | 'watch';
export const PLANS: Record<Plan, { title: string; short: string; note: string }> = {
  loop: { title: 'Follow a saved loop', short: 'Saved loop', note: 'Moves between platforms along a path you built.' },
  platform: { title: 'Stay on this platform', short: 'One platform', note: 'Hunts where you stand and never leaves the platform.' },
  watch: { title: 'Watch only', short: 'Watch only', note: 'Recognises and decides, but sends no keys.' },
};
export const PLAN_ORDER: Plan[] = ['loop', 'platform', 'watch'];
export const LENGTHS = [1, 15] as const;
export type Length = typeof LENGTHS[number];

export type LayerId = 'enemies' | 'range' | 'lines';
export const LAYERS: { id: LayerId; label: string }[] = [
  { id: 'enemies', label: 'Enemies' }, { id: 'range', label: 'Attack range' }, { id: 'lines', label: 'Map lines' },
];

export interface Check {
  id: string; label: string; ok: boolean;
  /** Completes "Can't start: …" when this is the first failing check. */
  miss: string;
  /** What the operator can do about it. */
  fix: string;
  /** Optional one-click fix the surface may offer. */
  action?: 'focus_game';
}

export interface CheckContext {
  connected: boolean; plan: Plan;
  /** Saved loops for the current map; undefined while unknown. */
  loops?: number;
}

const POTION_PROBES = ['hp_potion', 'mp_potion'];

/** The checks shown before every start, in the order an operator fixes them. The engine's own
    readiness gate is always last, so the list never claims ready when the engine says otherwise. */
export function startChecks(s: Snapshot | null | undefined, ctx: CheckContext): Check[] {
  const connected = ctx.connected && Boolean(s);
  const untested = s ? [...s.required_probes, ...POTION_PROBES.filter(p => p in s.probes)]
    .filter(p => !s.probes[p]?.confirmed) : [];
  const player = Boolean(s?.player) || (s?.player_tracking?.state != null && s.player_tracking.state !== 'lost');
  const checks: Check[] = [
    { id: 'engine', label: 'Engine connected', ok: connected, miss: 'the engine is not connected',
      fix: 'Start the engine, then reload this page.' },
    { id: 'restart', label: 'New keys in use', ok: !s?.key_settings?.restart_required,
      miss: 'the new keys need an engine restart', fix: 'Run .\\restart.ps1 in the project root, then test the changed keys.' },
    { id: 'focus', label: 'Game window in front', ok: connected && Boolean(s?.focused),
      miss: 'the game is behind another window', fix: 'Click Bring game to front.', action: 'focus_game' },
    { id: 'player', label: 'Character recognised', ok: connected && player,
      miss: "the character isn't recognised", fix: 'Stand still in view for two seconds.' },
    { id: 'map', label: 'Map recognised', ok: connected && Boolean(s?.position?.area_id),
      miss: "this map isn't recognised", fix: 'Open Maps and track or import this map.' },
    { id: 'keys', label: 'Keys set and tested', ok: connected && untested.length === 0,
      miss: untested.length === 1 ? `the ${keyLabel(untested[0])} key isn't tested` : "some keys aren't tested",
      fix: untested.length ? `Test ${untested.map(keyLabel).join(', ')} in Set up.` : '' },
  ];
  // Watch only sends no keys: it needs the engine, the character and the engine's own gate.
  if (ctx.plan === 'watch') checks.splice(0, checks.length, ...checks.filter(check => ['engine', 'restart', 'player'].includes(check.id)));
  if (ctx.plan === 'loop') checks.push({ id: 'loop', label: 'Saved loop on this map', ok: (ctx.loops ?? 0) > 0,
    miss: ctx.loops === undefined ? "saved loops aren't loaded yet" : 'this map has no saved loop',
    fix: 'Build a loop in Maps with the path builder.' });
  const gate = s?.readiness[ctx.plan === 'watch' ? 'preview' : 'combat'];
  checks.push({ id: 'gate', label: 'Safety checks pass', ok: connected && Boolean(gate?.ready),
    miss: gate?.reason ? lowerFirst(gate.reason) : 'the safety checks have not answered yet', fix: gate?.reason ?? '' });
  return checks;
}

export function firstBlocker(checks: Check[]): Check | null {
  return checks.find(check => !check.ok) ?? null;
}

const KEY_LABELS: Record<string, string> = {
  left: 'Left', right: 'Right', up: 'Up', down: 'Down', attack: 'Attack', jump: 'Jump', skill: 'Attack skill',
  hp_potion: 'HP potion', mp_potion: 'MP potion', pet_food: 'Pet food', emergency_key: 'Stop',
};
export function keyLabel(action: string): string { return KEY_LABELS[action] ?? action.replaceAll('_', ' '); }

/** The page title and its supporting sentence. */
export function statusSentence(state: BotState, blocker: Check | null, detail: { plan: Plan; loop?: string; minutes: number; reason?: string }) {
  const plan = PLANS[detail.plan];
  const what = `${plan.title}${detail.plan === 'loop' && detail.loop ? `: ${detail.loop}` : ''}`;
  if (state === 'disconnected') return { headline: 'The engine is not connected', detail: 'Nothing can start until it reconnects. No keys are sent.' };
  if (state === 'alarm') return { headline: 'Stopped. Move your character to safety.', detail: 'Keys released, clip saved and alarm sounded. It will not retry by itself.' };
  if (state === 'starting') return { headline: 'Starting', detail: 'Keep the game in front. Stop cancels.' };
  if (state === 'running') return { headline: detail.reason || 'Running', detail: `${what}.` };
  if (blocker) return { headline: `Can't start: ${blocker.miss}`, detail: blocker.fix };
  return { headline: 'Ready to hunt', detail: `${what}, ${detail.plan === 'watch' ? 'no keys' : `${detail.minutes} min`}.` };
}

/** "Waiting for X." → "waiting for X"; leaves acronyms such as "HP …" alone. */
function lowerFirst(text: string) {
  const trimmed = text.replace(/\.$/, '');
  return /^[A-Z][a-z]/.test(trimmed) ? trimmed[0].toLowerCase() + trimmed.slice(1) : trimmed;
}
