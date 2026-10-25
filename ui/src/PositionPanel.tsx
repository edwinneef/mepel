import { useState } from 'react';
import type { LivePosition, Snapshot } from './contracts';
import type { EngineClient } from './client';

type Act = (operation: () => Promise<unknown>) => Promise<void>;
interface PanelProps {
  snapshot: Snapshot; client: EngineClient; act: Act; disabled: boolean;
  areas: { id: string; name: string; revision: number }[];
}

export function positionLabel(position: LivePosition): string {
  if (position.kind === 'platform') return `On ${position.surface_id} · contact not verified`;
  return `Position unknown · ${position.reason}`;
}

export function PositionOverlay({ position }: { position: LivePosition | null | undefined }) {
  if (!position) return null;
  const canvas = position.canvas;
  const marker = canvas && position.marker ? { x: canvas.x + position.marker[0], y: canvas.y + position.marker[1] } : null;
  const at = canvas ? { x: canvas.x, y: canvas.y + canvas.height + 18 } : { x: 12, y: 24 };
  return <g className={`position-overlay ${position.kind}`} aria-label="Live position">
    {canvas && <rect x={canvas.x} y={canvas.y} width={canvas.width} height={canvas.height} className="position-canvas" />}
    {marker && <circle cx={marker.x} cy={marker.y} r="7" className="position-marker" />}
    <text x={at.x} y={at.y}>{positionLabel(position)}</text>
  </g>;
}

export function PositionPanel({ snapshot: s, client, act, disabled, areas }: PanelProps) {
  const [areaId, setAreaId] = useState('');
  const position = s.position;
  const walk = position?.calibration;
  const saved = walk?.saved;
  const command = (name: string, payload: Record<string, unknown> = {}) => act(() => client.command(name, payload));
  return <section className="tool-group"><h3>Live position · read only</h3>
    <p>Reads the minimap marker and name tag. Sends no input; a platform match does not prove contact.</p>
    <label>Track area<select value={areaId} onChange={event => setAreaId(event.target.value)}>
      <option value="">Choose a saved area…</option>{areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>
    <div className="button-grid"><button disabled={disabled || !areaId} onClick={() => void command('position_start', { area_id: areaId })}>Track position</button>
      <button disabled={disabled || !position} onClick={() => void command('position_stop')}>Stop tracking</button></div>
    {position && <>
      <p className="reading">{position.area_name ? `${position.area_name} · ` : ''}{positionLabel(position)}</p>
      <dl><div><dt>Feet</dt><dd>{position.feet ? `${position.feet[0].toFixed(0)}, ${position.feet[1].toFixed(0)}` : '—'}</dd></div>
        <div><dt>Minimap</dt><dd>{position.map ?? '—'}</dd></div>
        <div><dt>Calibration</dt><dd>{saved ? `${saved.pairs} pairs · p95 x ${saved.residual_px.x.p95.toFixed(1)} / y ${saved.residual_px.y.p95.toFixed(1)} px` : 'Not calibrated'}</dd></div></dl>
      <h3>Walk calibration</h3>
      <p>Begin, then walk the character yourself along the taught floor for about ten seconds. Pairs need a visible minimap marker and name tag.</p>
      {walk?.active && <p className="reading">{walk.pairs} pairs collected · {walk.rejected} frames without registration</p>}
      <div className="button-grid">{walk?.active ? <>
        <button disabled={disabled || walk.pairs < 10} onClick={() => void command('walk_calibration_finish')}>Finish and save</button>
        <button disabled={disabled} onClick={() => void command('walk_calibration_cancel')}>Cancel calibration</button></>
        : <button disabled={disabled || !position.area_id} onClick={() => void command('walk_calibration_begin')}>Begin walk calibration</button>}</div>
    </>}
  </section>;
}
