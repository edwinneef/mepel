import { useState } from 'react';
import type { LivePosition, Snapshot, TaughtGeometry } from './contracts';
import type { EngineClient } from './client';

type Act = (operation: () => Promise<unknown>) => Promise<void>;
interface PanelProps {
  snapshot: Snapshot; client: EngineClient; act: Act; disabled: boolean;
  areas: { id: string; name: string; revision: number }[]; refreshAreas: () => Promise<void>;
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

/** A plain drawing of the learned map: platforms, ropes, links and where you stand. */
export function MapSketch({ geometry, feet }: { geometry: TaughtGeometry; feet?: [number, number] | null }) {
  const b = geometry.boundary;
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
    {geometry.platforms.map(item => <line key={item.id} className="sketch-platform" x1={item.start.x} y1={item.start.y} x2={item.end.x} y2={item.end.y} />)}
    {geometry.ropes.map(item => <line key={item.id} className="sketch-rope" x1={item.start.x} y1={item.start.y} x2={item.end.x} y2={item.end.y} />)}
    {feet && <circle className="sketch-feet" cx={feet[0]} cy={feet[1]} r={Math.max(6, b.width / 120)} />}
  </svg>;
}

export function PositionPanel({ snapshot: s, client, act, disabled, areas, refreshAreas }: PanelProps) {
  const [areaId, setAreaId] = useState('');
  const [name, setName] = useState('');
  const position = s.position;
  const teaching = position?.teaching;
  const geometry = teaching?.geometry;
  const walk = position?.calibration;
  const saved = walk?.saved;
  const command = (name: string, payload: Record<string, unknown> = {}) => act(() => client.command(name, payload));
  const counts = geometry ? `${geometry.platforms.length} platforms · ${geometry.ropes.length} ropes · ${geometry.links.length} links` : 'nothing yet';
  return <section className="tool-group map-panel"><h3>Map</h3>
    <label>Saved map<select value={areaId} onChange={event => setAreaId(event.target.value)}>
      <option value="">Choose a map…</option>{areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>
    <div className="button-grid"><button disabled={disabled || !areaId} onClick={() => void command('position_start', { area_id: areaId })}>Track position</button>
      <button disabled={disabled || !position} onClick={() => void command('position_stop')}>Stop tracking</button></div>
    <details><summary>New map from this screen</summary>
      <p>Stand on the map with the full minimap open. The current screen becomes the map's reference.</p>
      <label>Map name<input value={name} onChange={event => setName(event.target.value)} placeholder="e.g. Blue Mushroom Forest" /></label>
      <button disabled={disabled} onClick={() => void act(async () => { const result = await client.command('teach_new_area', { name }); await refreshAreas(); return result; })}>Teach a new map</button>
    </details>
    {position && <>
      <p className="reading">{position.area_name ? `${position.area_name} · ` : ''}{positionLabel(position)}</p>
      {!teaching?.phase && <><p>Teach by playing: walk every floor and ledge end to end, and make each jump, drop and climb the bot may use. Takes one to three minutes. The bot sends no keys.</p>
        <button className="primary" disabled={disabled} onClick={() => void command('teach_begin')}>Teach this map</button></>}
      {teaching?.phase === 'calibrating' && <><p className="reading">Step 1 of 2 · Walk left and right along one floor · {walk?.pairs ?? 0} / 20</p>
        <button disabled={disabled} onClick={() => void command('teach_cancel')}>Cancel</button></>}
      {teaching?.phase === 'recording' && <><p className="reading">Step 2 of 2 · Recording: {counts}</p>
        <p>Visit each ledge, then press Finish.</p>
        <div className="button-grid"><button className="primary" disabled={disabled} onClick={() => void command('teach_finish')}>Finish</button>
          <button disabled={disabled} onClick={() => void command('teach_cancel')}>Cancel</button></div></>}
      {teaching?.phase === 'review' && <><p className="reading">Learned {counts}. Missing a ledge? Discard and walk it too.</p>
        <div className="button-grid"><button className="primary" disabled={disabled} onClick={() => void act(async () => { const result = await client.command('teach_save'); await refreshAreas(); return result; })}>Save map</button>
          <button disabled={disabled} onClick={() => void command('teach_cancel')}>Discard</button></div></>}
      {geometry && <MapSketch geometry={geometry} feet={position.feet} />}
      <details><summary>Walk calibration</summary>
        <p>{saved ? `${saved.pairs} pairs · p95 x ${saved.residual_px.x.p95.toFixed(1)} / y ${saved.residual_px.y.p95.toFixed(1)} px` : 'Not calibrated. Teaching calibrates automatically.'}</p>
        {walk?.active && !teaching?.phase && <p>{walk.pairs} pairs collected · {walk.rejected} frames without registration</p>}
        <div className="button-grid">{walk?.active && !teaching?.phase ? <>
          <button disabled={disabled || walk.pairs < 10} onClick={() => void command('walk_calibration_finish')}>Finish and save</button>
          <button disabled={disabled} onClick={() => void command('walk_calibration_cancel')}>Cancel calibration</button></>
          : <button disabled={disabled || Boolean(teaching?.phase)} onClick={() => void command('walk_calibration_begin')}>Recalibrate</button>}</div>
      </details>
    </>}
  </section>;
}
