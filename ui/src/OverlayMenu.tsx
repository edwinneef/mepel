import { useEffect, useRef, useState } from 'react';
import type { Snapshot } from './contracts';
import type { FarmingRoute } from './PathBuilder';
import { LayerToggles, LengthPicker, LoopChooser, Meter, PlanPicker, StateBadge } from './ClearParts';
import { botState } from './vocabulary';
import type { Plan } from './vocabulary';

/** Saved farming paths for the map the player is on, as the widget last read them. */
export type PathAvailability =
  | { state: 'unknown' } | { state: 'loading' } | { state: 'error'; message: string }
  | { state: 'ready'; names: string[]; routes?: FarmingRoute[] };

/** One line: whether this map has a saved path, in words as well as colour. */
export function pathSummary(paths: PathAvailability | undefined, area: string | null | undefined) {
  if (!area || !paths || paths.state === 'unknown') return { tone: 'muted', text: 'map not recognised', title: 'Saved paths show once the bot knows which map this is.' };
  if (paths.state === 'loading') return { tone: 'muted', text: 'checking…', title: 'Reading saved paths for this map.' };
  if (paths.state === 'error') return { tone: 'muted', text: 'unavailable', title: paths.message };
  if (!paths.names.length) return { tone: 'none', text: 'none on this map', title: 'Build one in the dashboard: Map, then the path builder.' };
  const [first, ...rest] = paths.names;
  return { tone: 'ready', text: rest.length ? `${first} +${rest.length}` : first,
    title: `${paths.names.length} saved for this map: ${paths.names.join(', ')}. Choose one in the dashboard to farm it.` };
}

export interface BatchState { running: boolean; kind?: string; line?: string; output?: string; code?: number;
  /** A dashboard start the in-game overlay has not taken yet. */
  pending?: boolean }
type Rect = { x: number; y: number; width: number; height: number };

const WIDTH = 300;
const HEIGHT = 360;

/** Where the menu goes: beside the game view, never over it.

Live: over the game's top-right it covered one of the engine's coverage sample points
(5%, 50% and 95% of the view in each direction) whenever it took the mouse, so the
engine saw the game as covered (which also refuses gameplay input) and the menu vanished
under the cursor. Inside the view is a last resort, clear of every sample point.
*/
export function menuPlacement(game: Rect, viewport: { width: number; height: number }) {
  const top = Math.max(0, Math.min(game.y, viewport.height - HEIGHT));
  if (game.x + game.width + 8 + WIDTH <= viewport.width) return { left: game.x + game.width + 8, top };
  if (game.x - 8 - WIDTH >= 0) return { left: game.x - 8 - WIDTH, top };
  return { left: game.x + Math.round(game.width * .55), top: game.y + Math.round(game.height * .06) + 4 };
}

/** Folded height of the docked widget: just its header bar (layout pixels, before DOCK_SCALE). */
export const FOLDED_HEIGHT = 42;
/** The docked widget is drawn smaller so it fits left of MapleStory's chat box. */
export const DOCK_SCALE = .82;
const DOCK_MARGIN = 8;

/** Bottom-left dock inside the game picture, clear of every coverage sample point.

Flush with the game's left edge, it crosses the 5% sample column, so it stays between the
50% and 95% sample rows: the folded bar sits just above the 95% row (`bottom`, in page
pixels) and opening grows it upward, never past the 50% row. It is scaled by DOCK_SCALE
from its bottom-left corner; `openHeight` and `top` are layout values before that scale.
Returns null when the game picture is too small or runs off the bottom of the overlay.
*/
export function dockPlacement(game: Rect, viewport: { width: number; height: number }) {
  const left = game.x + DOCK_MARGIN;
  const right = game.x + Math.floor(game.width * .5) - DOCK_MARGIN;
  const top = game.y + Math.ceil(game.height * .5) + DOCK_MARGIN;
  const bottom = game.y + Math.floor(game.height * .95) - DOCK_MARGIN;
  const room = bottom - top;
  if (right - left < WIDTH * DOCK_SCALE || room < 200 || bottom > viewport.height) return null;
  // Placed by its top edge from the game picture alone, so no window-height reading can shift it.
  const openHeight = Math.min(HEIGHT, Math.floor(room / DOCK_SCALE));
  return { left, bottom, openHeight, top: (open: boolean) => bottom - (open ? openHeight : FOLDED_HEIGHT) };
}

/** Frames per second the engine is analysing, from its own count or the frame interval. */
export function engineFps(s: Snapshot | null | undefined): number | null {
  if (typeof s?.fps === 'number' && Number.isFinite(s.fps) && s.fps > 0) return s.fps;
  const interval = s?.stage_timing?.capture_interval_ms;
  return typeof interval === 'number' && interval > 0 ? 1000 / interval : null;
}

/** The batch tool prints one JSON line at the end; show its result in plain words. */
export function batchSummary(batch: BatchState): string | null {
  const text = (batch.output ?? batch.line ?? '').trim();
  if (!text) return null;
  const lines = text.split(/\r?\n/).filter(Boolean);
  for (const line of [...lines].reverse()) {
    try {
      const value = JSON.parse(line) as Record<string, unknown>;
      if (typeof value.blocked === 'string') return `Refused, no keys sent: ${value.blocked}`;
      if (typeof value.outcome === 'string') {
        const proven = typeof value.proven_after === 'number' ? ` · ${value.proven_after} moves proven` : '';
        const why = value.outcome === 'functional_success' ? 'Finished the full session'
          : value.outcome === 'nothing_left' ? 'Nothing left to do; stopped cleanly'
          : `Stopped: ${String(value.error ?? value.outcome)}`;
        return why + proven;
      }
      if (typeof value.error === 'string') return `Stopped: ${value.error}`;
    } catch { /* not the result line */ }
  }
  return lines[lines.length - 1];
}

export interface BatchReport { tone: 'ok' | 'fail' | 'info'; headline: string; detail: string }

/** What happened in the last batch, in plain words: a one-line headline and the reasons. */
export function batchReport(batch: BatchState): BatchReport | null {
  const text = (batch.output ?? batch.line ?? '').trim();
  if (!text) return null;
  const lines = text.split(/\r?\n/).filter(Boolean);
  for (const line of [...lines].reverse()) {
    let value: Record<string, unknown>;
    try { value = JSON.parse(line) as Record<string, unknown>; } catch { continue; }
    if (typeof value.blocked === 'string') {
      return { tone: 'fail', headline: 'Not started · no keys sent', detail: value.blocked };
    }
    if (typeof value.outcome !== 'string' && typeof value.error !== 'string') continue;
    const stop = (value.stop ?? {}) as { code?: string; message?: string };
    const misses = Array.isArray(value.misses) ? value.misses.length : 0;
    const extras = [
      typeof value.proven_after === 'number' ? `${value.proven_after} moves proven` : '',
      misses ? `${misses} missed ${misses === 1 ? 'move' : 'moves'} landed safely` : '',
    ].filter(Boolean).join(' · ');
    if (value.outcome === 'functional_success') {
      return { tone: 'ok', headline: 'Finished the full session', detail: extras };
    }
    if (value.outcome === 'nothing_left') {
      return { tone: 'ok', headline: 'Nothing left to do · stopped cleanly', detail: extras };
    }
    const reasons = [
      typeof value.error === 'string' && value.error ? `Why: ${value.error}` : '',
      stop.message && stop.message !== value.error ? `Engine stop${stop.code ? ` (${stop.code})` : ''}: ${stop.message}` : '',
      typeof value.stop_error === 'string' && value.stop_error ? `Stop problem: ${value.stop_error}` : '',
      extras,
      batch.code !== undefined && batch.code !== 0 ? 'Keys released, clip saved. Move to safety; no automatic retry.' : '',
    ].filter(Boolean);
    return value.outcome === 'safe_stop'
      ? { tone: 'info', headline: 'Stopped safely', detail: reasons.join('\n') }
      : { tone: 'fail', headline: 'Run failed', detail: reasons.join('\n') || 'No reason was reported; see the result file.' };
  }
  return { tone: batch.code ? 'fail' : 'info', headline: batch.code ? 'Run ended with an error' : 'Last batch',
    detail: lines.slice(-3).join('\n') };
}

/** Small in-game menu (design 2a): state and Stop, then the same plan, loop and length choices as the dashboard. */
export function OverlayMenu({ s, status, game, layers, attackRange, names, setLayers, setAttackRange, setNames,
  batch, canBatch, onStart, onStop, startBlocker, paths }: {
  paths?: PathAvailability;
  startBlocker?: string;
  s: Snapshot | null; status: string; game: Rect;
  layers: boolean; attackRange: boolean; names: boolean;
  setLayers(value: boolean): void; setAttackRange(value: boolean): void; setNames(value: boolean): void;
  batch: BatchState; canBatch: boolean;
  onStart(kind: 'learn' | 'single', circuit?: { id: string; revision: number }, minutes?: number): void; onStop(): void;
}) {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<Plan>('loop');
  const [selectedRoute, setSelectedRoute] = useState('');
  const [minutes, setMinutes] = useState(1);
  const routes = paths?.state === 'ready' ? (paths.routes ?? []).filter(route => route.loop) : [];
  const circuit = routes.find(route => route.id === selectedRoute && route.area_id === s?.position?.area_id);
  const menu = useRef<HTMLElement>(null);
  const reported = useRef('');
  // Re-report the mouse area when the slide finishes; the rect only settles after the transition.
  const [, setSettled] = useState(0);
  const [offset, setOffset] = useState<{ left: number; top: number } | null>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  // Tell the overlay host where the menu is, so only that area takes the mouse. Report only
  // changes: clearing the area on every re-render (about five per second) made the overlay
  // switch mouse capture and topmost on and off under the cursor, and the menu flickered.
  useEffect(() => {
    const rect = menu.current?.getBoundingClientRect();
    const rects = rect ? [{ x: Math.round(rect.x), y: Math.round(rect.y),
      width: Math.round(rect.width), height: Math.round(rect.height) }] : [];
    const key = JSON.stringify(rects);
    if (key === reported.current) return;
    reported.current = key;
    window.mapleOverlay?.interactive?.(rects);
  });
  useEffect(() => () => window.mapleOverlay?.interactive?.([]), []);
  const fps = engineFps(s);
  const where = s?.position?.surface_id ?? null;
  const busy = batch.running || status === 'ON' || status === 'STARTING';
  const state = botState(status, batch.running);
  const area = s?.position?.area_id;
  const mapName = area ? s?.position?.area_name || 'Saved map' : null;
  const summary = batchSummary(batch);
  // The first thing stopping a start, in the same words as the dashboard.
  const blocker = busy ? null : status === 'DISCONNECTED' ? 'the engine is not connected'
    : startBlocker ? startBlocker : !canBatch ? 'the dashboard is not connected'
    : !area ? "this map isn't recognised" : plan === 'watch' ? 'Watch only starts from the dashboard'
    : plan === 'loop' && !routes.length ? 'this map has no saved loop'
    : plan === 'loop' && !circuit ? 'choose a saved loop' : null;
  const ready = !busy && !blocker;
  const start = () => plan === 'loop' ? circuit && onStart('learn', { id: circuit.id, revision: circuit.revision }, minutes)
    : onStart('single', undefined, minutes);
  // A fixed-size report box, so the open menu keeps its height as messages change.
  const report: BatchReport | null = batch.running
    ? { tone: 'info', headline: 'Progress', detail: summary ?? '' }
    : startBlocker ? { tone: 'info', headline: 'Cannot start yet', detail: startBlocker } : batchReport(batch);
  const headline = state === 'alarm' ? 'Stopped. Move your character to safety.' : busy ? `Running${where ? ` on ${where}` : ''}`
    : blocker ? `Can't start: ${blocker}` : 'Ready to hunt';
  const whereText = `${mapName ?? 'Map not recognised'}${where ? ` · ${where}` : ''}`;
  const viewport = { width: window.innerWidth, height: window.innerHeight };
  // Docked bottom-left inside the game picture unless dragged; it grows upward when opened.
  const dock = offset ? null : dockPlacement(game, viewport);
  const style = dock
    ? { left: dock.left, top: dock.top(open), width: WIDTH, height: open ? dock.openHeight : FOLDED_HEIGHT,
      transform: `scale(${DOCK_SCALE})`, transformOrigin: 'bottom left' }
    : { ...(offset ?? menuPlacement(game, viewport)), width: WIDTH };
  const toggles = { enemies: layers, range: attackRange, lines: names };
  const potion = s?.autopotter;
  return <section ref={menu} className={`overlay-menu clear-widget ${open ? 'is-open' : 'is-folded'}${dock ? ' is-docked' : ''}`}
    aria-label="Bot menu" style={style}
    onTransitionEnd={event => { if (event.target === event.currentTarget) setSettled(value => value + 1); }}>
    <header className="w-head" title="Drag to move" onPointerDown={event => {
      if (event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
      const rect = menu.current!.getBoundingClientRect();
      drag.current = { x: event.clientX, y: event.clientY, left: rect.left, top: rect.top };
      event.currentTarget.setPointerCapture(event.pointerId);
      event.preventDefault();
    }} onPointerMove={event => {
      const current = drag.current;
      if (!current) return;
      const height = menu.current?.offsetHeight ?? 40;
      setOffset({ left: Math.max(0, Math.min(innerWidth - WIDTH, current.left + event.clientX - current.x)),
        top: Math.max(0, Math.min(innerHeight - height, current.top + event.clientY - current.y)) });
    }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
      <button className="w-fold" aria-expanded={open} aria-label={open ? 'Fold menu' : 'Open menu'}
        onClick={() => setOpen(value => !value)}>{open ? '▾' : dock ? '▴' : '▸'}</button>
      <StateBadge state={state} />
      <span className="w-fps">{fps == null ? '– fps' : `${fps.toFixed(1)} fps`}</span>
      <button className="c-btn stop small w-stop" disabled={!busy} onClick={onStop} aria-label="Stop (F8)" title="Stop (F8)">Stop</button>
    </header>
    {open && <div className="w-body">
      <p className="w-line" title={headline}>{headline}</p>
      <p className="w-where" title={mapName ?? s?.auto_track?.last ?? 'The minimap does not match a saved map yet.'}>{whereText}</p>
      {busy ? <div className="w-running">
        <Meter label="HP" kind="hp" percent={potion?.readings.hp?.percent} threshold={potion?.settings.hp_threshold ?? 50} />
        <Meter label="MP" kind="mp" percent={potion?.readings.mp?.percent} threshold={potion?.settings.mp_threshold ?? 50} />
      </div> : <>
        <PlanPicker compact plan={plan} onPlan={setPlan} available={{ watch: 'Start Watch only from the dashboard.' }} />
        <div className="w-row"><LoopChooser plan={plan} selected={circuit?.id ?? null} onSelect={setSelectedRoute}
          loops={paths?.state === 'ready' ? routes.map(route => ({ id: route.id, name: `${route.name} · r${route.revision}`, stops: route.stops.length })) : area ? undefined : []} /></div>
        <div className="w-row"><LengthPicker plan={plan} minutes={minutes} onMinutes={setMinutes} /></div>
        <button className="c-btn start w-start" disabled={!ready} onClick={start}
          title={plan === 'loop' ? 'Follow the selected loop using confirmed HP/MP potion keys' : 'Hunt on the platform you stand on; uses your confirmed potion keys'}>Start</button>
      </>}
      <LayerToggles values={toggles} onToggle={id => id === 'enemies' ? setLayers(!layers) : id === 'range' ? setAttackRange(!attackRange) : setNames(!names)} />
      <div className={`w-report tone-${report?.tone ?? 'info'}`} role="status">
        {report ? <><strong>{report.headline}</strong><p>{report.detail}</p></>
          : <p className="w-empty">The result of the next run shows here.</p>}
      </div>
    </div>}
  </section>;
}
