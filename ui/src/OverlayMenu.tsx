import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { Snapshot } from './contracts';

export interface BatchState { running: boolean; kind?: string; line?: string; output?: string; code?: number }
type Rect = { x: number; y: number; width: number; height: number };

const WIDTH = 236;
const HEIGHT = 250;  // generous: the open menu is about 230 px tall

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
  batch, canBatch, onStart, onStop, capture }: {
  capture?: ReactNode;
  s: Snapshot | null; status: string; game: Rect;
  layers: boolean; attackRange: boolean; names: boolean;
  setLayers(value: boolean): void; setAttackRange(value: boolean): void; setNames(value: boolean): void;
  batch: BatchState; canBatch: boolean;
  onStart(kind: 'learn' | 'single'): void; onStop(): void;
}) {
  const [open, setOpen] = useState(false);
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
      <p className="overlay-menu-where">{where ? `Standing on ${where}` : 'Position unknown'}
        {s?.stop?.message && !busy ? ` · last stop: ${s.stop.message}` : ''}</p>
      {capture}
      <div className="overlay-menu-switches">
        <label><input type="checkbox" checked={layers} onChange={e => setLayers(e.target.checked)} /><span className="overlay-menu-icon" aria-hidden="true">◉</span><span>Enemies</span></label>
        <label><input type="checkbox" checked={attackRange} onChange={e => setAttackRange(e.target.checked)} /><span className="overlay-menu-icon" aria-hidden="true">◎</span><span>Range</span></label>
        <label><input type="checkbox" checked={names} onChange={e => setNames(e.target.checked)} /><span className="overlay-menu-icon" aria-hidden="true">▧</span><span>Map</span></label>
      </div>
      <div className="overlay-menu-actions">
        <button disabled={!ready} onClick={() => onStart('learn')}
          title="5 minutes; learns new moves while farming; no potions, stops at 50% HP/MP">Start run</button>
        <button disabled={!ready} onClick={() => onStart('single')}
          title="15 minutes on the platform you stand on; uses your confirmed potion keys">Start single platform</button>
      </div>
      {summary && <p className="overlay-menu-result" role="status">{batch.running ? summary : `Last batch: ${summary}`}</p>}
    </>}
  </section>;
}
