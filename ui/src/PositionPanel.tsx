import { useState } from 'react';
import type { LivePosition, Snapshot, TaughtGeometry } from './contracts';
import type { EngineClient } from './client';

type Act = (operation: () => Promise<unknown>) => Promise<void>;
interface PanelProps {
  snapshot: Snapshot; client: EngineClient; act: Act; disabled: boolean;
  areas: { id: string; name: string; revision: number }[]; refreshAreas: () => Promise<void>;
}

export function positionLabel(position: LivePosition): string {
  if (position.kind === 'platform' && position.provisional) return 'Provisional middle-ledge match · observation only';
  if (position.kind === 'platform') return `On ${position.surface_id} · contact not verified`;
  return `Position unknown · ${position.reason}`;
}

export function PositionOverlay({ position, showText = true }: { position: LivePosition | null | undefined; showText?: boolean }) {
  if (!position) return null;
  const canvas = position.canvas;
  const marker = canvas && position.marker ? { x: canvas.x + position.marker[0], y: canvas.y + position.marker[1] } : null;
  const at = canvas ? { x: canvas.x, y: canvas.y + canvas.height + 18 } : { x: 12, y: 24 };
  return <g className={`position-overlay ${position.kind}`} aria-label="Live position">
    {canvas && <rect x={canvas.x} y={canvas.y} width={canvas.width} height={canvas.height} className="position-canvas" />}
    {marker && <circle cx={marker.x} cy={marker.y} r="7" className="position-marker" />}
    {showText && <text x={at.x} y={at.y}>{positionLabel(position)}</text>}
  </g>;
}

/** walk_p3 → P3, walk_r1 → R1: short names shared by the sketch and the problem list. */
export function label(id: string): string {
  const match = /^walk_([pr])(\d+)$/.exec(id);
  return match ? `${match[1].toUpperCase()}${match[2]}` : id;
}

/** A plain drawing of the learned map: platforms, ropes, links and where you stand. */
export function MapSketch({ geometry, feet }: { geometry: TaughtGeometry; feet?: [number, number] | null }) {
  const b = geometry.boundary;
  const bad = new Set([...(geometry.problems?.unreachable ?? []), ...(geometry.problems?.stranded ?? [])]);
  if (!b) return null;
  const nodes = [...geometry.platforms, ...geometry.ropes];
  const middle = (id: string) => {
    const node = nodes.find(item => item.id === id);
    return node ? { x: (node.start.x + node.end.x) / 2, y: (node.start.y + node.end.y) / 2 } : null;
  };
  return <svg className="map-sketch" viewBox={`${b.x} ${b.y} ${b.width} ${b.height}`} role="img" aria-label="Learned map">
    {geometry.links.map(link => {
      const a = middle(link.from), c = middle(link.to);
      return a && c ? <line key={link.id} className={`sketch-link ${link.kind}`} x1={a.x} y1={a.y} x2={c.x} y2={c.y} /> : null;
    })}
    {geometry.platforms.map(item => <g key={item.id}><line className={`sketch-platform ${bad.has(item.id) ? 'problem' : ''}`} x1={item.start.x} y1={item.start.y} x2={item.end.x} y2={item.end.y} />
      <text className="sketch-label" x={item.start.x} y={item.start.y - 8} fontSize={Math.max(12, b.width / 60)}>{label(item.id)}</text></g>)}
    {geometry.ropes.map(item => <g key={item.id}><line className={`sketch-rope ${bad.has(item.id) ? 'problem' : ''}`} x1={item.start.x} y1={item.start.y} x2={item.end.x} y2={item.end.y} />
      <text className="sketch-label" x={item.start.x + 6} y={item.start.y} fontSize={Math.max(12, b.width / 60)}>{label(item.id)}</text></g>)}
    {feet && <circle className="sketch-feet" cx={feet[0]} cy={feet[1]} r={Math.max(6, b.width / 120)} />}
  </svg>;
}

export function PositionPanel({ snapshot: s, client, act, disabled, areas }: PanelProps) {
  const [chosenArea, setChosenArea] = useState('');
  const position = s.position;
  const calibration = position?.calibration;
  const calibrating = Boolean(calibration?.active);
  const mapId = chosenArea || position?.area_id || '';
  const command = (action: string, payload: Record<string, unknown> = {}) => act(() => client.command(action, payload));
  let title = 'Choose a map';
  let instruction = 'Pick a saved map to track. Tracking sends no game keys.';
  if (position) {
    title = position.calibrated ? 'Tracking this map' : 'Walk calibration needed';
    instruction = position.calibrated ? positionLabel(position) : 'Start walk calibration, then walk left and right on one floor so the minimap can be matched to the map.';
  }
  if (calibrating) {
    title = 'Learning how the map scrolls';
    instruction = `Walk left and right on one floor · ${calibration?.pairs ?? 0} samples (${calibration?.rejected ?? 0} rejected). Finish once you have covered the floor; no game keys are sent.`;
  }
  return <section className="teaching-panel" aria-label="Map setup">
    <div className="teaching-summary">
      <span className="eyebrow">{position?.area_name ?? 'Map setup'}</span><h3>{title}</h3><p>{instruction}</p>
      <label>Saved map<select aria-label="Saved map" value={mapId} onChange={event => setChosenArea(event.target.value)}><option value="">Choose a map…</option>{areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>
      <div className="button-grid">
        <button className="primary" disabled={disabled || !mapId} onClick={() => void command('position_start', { area_id: mapId })}>{position ? 'Switch / reconnect map' : 'Track selected map'}</button>
        <button disabled={disabled || !position} onClick={() => void command('position_stop')}>Stop tracking</button>
      </div>
      {s.capture_only && position?.supplement?.available && <div className="saved-map-note">
        <button aria-pressed={position.supplement.enabled}
          disabled={disabled || calibrating || s.mode !== 'capture' || Boolean(s.area_editing)}
          onClick={() => void command('position_supplement', { enabled: !position.supplement?.enabled })}>
          {position.supplement.enabled ? 'Stop observing middle ledge' : 'Observe middle ledge'}</button>
        <p>Session only · provisional screenshot coverage. The saved map and movement routes stay unchanged.</p>
      </div>}
    </div>
    <p className="saved-map-note">Platforms, ropes and moves come from public map data. Save a new map once with a reference view (Advanced: draw by hand), then stop the engine and run <code>maplebot import-map "&lt;map name&gt;"</code> and start the engine again.</p>
    <details className="teaching-options" open={calibrating || undefined}><summary>Walk calibration</summary>
      <p>{s.health?.reason ?? position?.reason ?? 'Track a map to see position status.'}</p>
      <p>{calibration?.saved ? `${calibration.saved.pairs} saved calibration samples` : 'This map has no walk calibration yet.'}</p>
      <div className="button-grid">{calibrating ? <>
        <button disabled={disabled} onClick={() => void command('walk_calibration_finish')}>Finish calibration</button>
        <button disabled={disabled} onClick={() => void command('walk_calibration_cancel')}>Cancel calibration</button>
      </> : <button disabled={disabled || !position} onClick={() => void command('walk_calibration_begin')}>{calibration?.saved ? 'Recalibrate' : 'Start walk calibration'}</button>}</div>
    </details>
  </section>;
}
