import { useEffect, useRef, useState } from 'react';
import type { Snapshot } from './contracts';
import type { FarmingRoute } from './PathBuilder';

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

export interface BatchState { running: boolean; kind?: string; line?: string; output?: string; code?: number }
type Rect = { x: number; y: number; width: number; height: number };

const WIDTH = 236;
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

/** Small in-game menu: what the bot is doing, display switches and the two batch starts. */
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
  const [selectedRoute, setSelectedRoute] = useState('');
  const [minutes, setMinutes] = useState(1);
  const routes = paths?.state === 'ready' ? (paths.routes ?? []).filter(route => route.loop) : [];
  const circuit = routes.find(route => route.id === selectedRoute && route.area_id === s?.position?.area_id);
  const menu = useRef<HTMLElement>(null);
  const reported = useRef('');
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
  const ready = canBatch && !busy && Boolean(s?.position?.area_id) && status !== 'DISCONNECTED';
  const summary = batchSummary(batch);
  // One fixed line for status text, so the open menu keeps its height as messages change.
  const note = batch.running ? summary ?? '' : startBlocker ?? (summary ? `Last batch: ${summary}` : '');
  const whereText = `${where ? `Standing on ${where}` : 'Position unknown'}${s?.stop?.message && !busy ? ` · last stop: ${s.stop.message}` : ''}`;
  const style = { ...(offset ?? menuPlacement(game, { width: window.innerWidth, height: window.innerHeight })), width: WIDTH };
  return <section ref={menu} className={`overlay-menu ${open ? "is-open" : "is-folded"}`} aria-label="Bot menu" style={style}>
    <header title="Drag to move" onPointerDown={event => {
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
      <button className="overlay-menu-fold" aria-expanded={open} aria-label={open ? 'Fold menu' : 'Open menu'}
        onClick={() => setOpen(value => !value)}>{open ? '▾' : '▸'}</button>
      <strong className={`overlay-menu-state state-${status.toLowerCase()}`}>
        {batch.running ? 'Batch running' : status}</strong>
      <span className="overlay-menu-fps">{fps == null ? '– fps' : `${fps.toFixed(1)} fps`}</span>
      <button className="overlay-menu-stop" disabled={!busy} onClick={onStop} aria-label="Stop (F8)" title="Stop (F8)">■</button>
    </header>
    {open && <>
      <p className="overlay-menu-where overlay-menu-line" title={whereText}>{whereText}</p>
      {(() => { const path = pathSummary(paths, s?.position?.area_id); return <p className={`overlay-menu-path tone-${path.tone}`} title={path.title}>
        <span className="overlay-menu-path-dot" aria-hidden="true" /><span className="overlay-menu-path-key">Path</span><span className="overlay-menu-path-value">{path.text}</span></p>; })()}
      <div className="overlay-menu-switches">
        <label><input type="checkbox" checked={layers} onChange={e => setLayers(e.target.checked)} /><span className="overlay-menu-icon" aria-hidden="true">◉</span><span>Enemies</span></label>
        <label><input type="checkbox" checked={attackRange} onChange={e => setAttackRange(e.target.checked)} /><span className="overlay-menu-icon" aria-hidden="true">◎</span><span>Range</span></label>
        <label><input type="checkbox" checked={names} onChange={e => setNames(e.target.checked)} /><span className="overlay-menu-icon" aria-hidden="true">▧</span><span>Map</span></label>
      </div>
      <label>Farming circuit<select aria-label="Farming circuit" value={circuit?.id ?? ''} disabled={busy}
        onChange={event => setSelectedRoute(event.target.value)}>
        <option value="">Choose a saved loop</option>
        {routes.map(route => <option key={route.id} value={route.id}>{route.name} · r{route.revision}</option>)}
      </select></label>
      <label>Run duration<select aria-label="Run duration" value={minutes} disabled={busy}
        onChange={event => setMinutes(Number(event.target.value))}>
        <option value={1}>1 minute</option><option value={15}>15 minutes</option>
      </select></label>
      <p className="overlay-menu-result">HP/MP potions · food F every 10 min</p>
      <div className="overlay-menu-actions">
        <button disabled={!ready || !circuit} onClick={() => circuit && onStart('learn', { id: circuit.id, revision: circuit.revision }, minutes)}
          title="Follow the selected loop using confirmed HP/MP potion keys">Start run</button>
        <button disabled={!ready} onClick={() => onStart('single')}
          title="15 minutes on the platform you stand on; uses your confirmed potion keys">Start single platform</button>
      </div>
      <p className="overlay-menu-result overlay-menu-line" role="status" title={note}>{note || ' '}</p>
    </>}
  </section>;
}
