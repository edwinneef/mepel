import { useState } from 'react';
import type { Snapshot } from './contracts';

export interface BatchState { running: boolean; kind?: string; line?: string; output?: string; code?: number }
type Rect = { x: number; y: number; width: number; height: number };

const WIDTH = 236;

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
  batch, canBatch, onStart, onStop }: {
  s: Snapshot | null; status: string; game: Rect;
  layers: boolean; attackRange: boolean; names: boolean;
  setLayers(value: boolean): void; setAttackRange(value: boolean): void; setNames(value: boolean): void;
  batch: BatchState; canBatch: boolean;
  onStart(kind: 'learn' | 'single'): void; onStop(): void;
}) {
  const [open, setOpen] = useState(true);
  const fps = engineFps(s);
  const where = s?.position?.surface_id ?? null;
  const busy = batch.running || status === 'ON' || status === 'STARTING';
  const ready = canBatch && !busy && Boolean(s?.position?.area_id) && status !== 'DISCONNECTED';
  const summary = batchSummary(batch);
  const style = { left: Math.max(game.x + 8, game.x + game.width - WIDTH - 8), top: game.y + 8, width: WIDTH };
  return <section className="overlay-menu" aria-label="Bot menu" style={style}>
    <header>
      <button className="overlay-menu-fold" aria-expanded={open} aria-label={open ? 'Fold menu' : 'Open menu'}
        onClick={() => setOpen(value => !value)}>{open ? '▾' : '▸'}</button>
      <strong className={`overlay-menu-state state-${status.toLowerCase()}`}>
        {batch.running ? 'BATCH RUNNING' : status}</strong>
      <span className="overlay-menu-fps">{fps == null ? '– fps' : `${fps.toFixed(1)} fps`}</span>
    </header>
    {open && <>
      <p className="overlay-menu-where">{where ? `Standing on ${where}` : 'Position unknown'}
        {s?.stop?.message && !busy ? ` · last stop: ${s.stop.message}` : ''}</p>
      <div className="overlay-menu-switches">
        <label><input type="checkbox" checked={layers} onChange={e => setLayers(e.target.checked)} /> Show detection boxes</label>
        <label><input type="checkbox" checked={attackRange} onChange={e => setAttackRange(e.target.checked)} /> Show attack range</label>
        <label><input type="checkbox" checked={names} onChange={e => setNames(e.target.checked)} /> Show platform names</label>
      </div>
      <div className="overlay-menu-actions">
        <button disabled={!ready} onClick={() => onStart('learn')}
          title="5 minutes; learns new moves while farming; no potions, stops at 50% HP/MP">Start run</button>
        <button disabled={!ready} onClick={() => onStart('single')}
          title="15 minutes on the platform you stand on; uses your confirmed potion keys">Start single platform</button>
        <button className="overlay-menu-stop" disabled={!busy} onClick={onStop}>Stop (F8)</button>
      </div>
      {summary && <p className="overlay-menu-result" role="status">{batch.running ? summary : `Last batch: ${summary}`}</p>}
    </>}
  </section>;
}
