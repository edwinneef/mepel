import { useState } from 'react';
import type { LivePosition, Snapshot, TaughtGeometry } from './contracts';
import type { EngineClient } from './client';
import { placeName, TeachingTerrain } from './TeachingTerrain';

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

function problemText(geometry: TaughtGeometry): string[] {
  const problems = geometry.problems;
  if (!problems?.home) return [];
  const lines = [];
  if (problems.unreachable.length) lines.push(`No journey recorded from ${label(problems.home)} to: ${problems.unreachable.map(label).join(', ')}.`);
  if (problems.stranded.length) lines.push(`No return journey recorded to ${label(problems.home)} from: ${problems.stranded.map(label).join(', ')}.`);
  return lines;
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

export function PositionPanel({ snapshot: s, client, act, disabled, areas, refreshAreas }: PanelProps) {
  const [chosenArea, setChosenArea] = useState('');
  const [name, setName] = useState('');
  const [selected, setSelected] = useState('');
  const [confirmation, setConfirmation] = useState<{ platforms_before?: number; platforms_after?: number; zones_removed?: number } | null>(null);
  const [discard, setDiscard] = useState(false);
  const [report, setReport] = useState('');
  const [copied, setCopied] = useState(false);
  const [saveError, setSaveError] = useState('');
  const position = s.position;
  const teaching = position?.teaching;
  const phase = teaching?.phase;
  const geometry = teaching?.geometry;
  const draft = teaching?.draft;
  const mapId = chosenArea || position?.area_id || '';
  const nodes = geometry ? [...geometry.platforms, ...geometry.ropes] : [];
  const issues = geometry?.problems;
  const missing = [...(issues?.unreachable ?? []), ...(issues?.stranded ?? [])];
  let selection = selected || missing[0] || nodes[0]?.id;
  for (let i = 0; selection && geometry?.aliases?.[selection] && i < 20; i++) selection = geometry.aliases[selection];
  const place = nodes.find(item => item.id === selection) ?? nodes.find(item => item.id === missing[0]) ?? nodes[0];
  const home = nodes.find(item => item.id === issues?.home);
  const stranded = Boolean(place && issues?.stranded.includes(place.id));
  const unreachable = Boolean(place && issues?.unreachable.includes(place.id));
  const target = stranded ? home : unreachable ? home : undefined;
  const health = teaching?.health;
  // A tracking report belongs to the review; continuing to teach must still be able to finish.
  const lost = phase === 'review' && Boolean(missing.length && health?.misses);
  const command = (action: string, payload: Record<string, unknown> = {}) => act(() => client.command(action, payload));
  const activate = (confirm = false) => act(async () => {
    setSaveError('');
    let result: { requires_confirmation?: boolean; platforms_before?: number; platforms_after?: number; zones_removed?: number };
    try { result = await client.command('teach_save', confirm ? { confirm_partial: true } : {}); }
    catch (error) { setSaveError(error instanceof Error ? error.message : String(error)); return; }
    if (result.requires_confirmation) setConfirmation(result);
    else { setConfirmation(null); await refreshAreas(); }
    return result;
  });
  const copyReport = async () => {
    const text = JSON.stringify({ area: position?.area_name, draft, health,
      currentHealth: s.health, issue: issues, evidence: teaching?.evidence }, null, 2);
    try { await navigator.clipboard.writeText(text); setCopied(true); setReport(''); }
    catch { setReport(text); setCopied(false); }
  };
  let title = 'Choose a map';
  let instruction = 'Pick a saved map to track. To record a new one, use Teach a new map under Other map actions. Teaching sends no game keys.';
  let action = 'Track selected map';
  let run = () => command('position_start', { area_id: mapId });
  let blocked = disabled || !mapId;
  if (position) {
    blocked = disabled;
    title = teaching?.map_receipt ? 'Map saved' : 'Ready to teach';
    instruction = teaching?.map_receipt ? `Saved map revision ${teaching.map_receipt.revision}. Gameplay stays stopped.` : 'Walk the places you want the bot to learn. Your teaching draft is saved separately from the map in use.';
    action = 'Teach this map'; run = () => command('teach_begin');
  }
  if (phase === 'calibrating') {
    title = 'Learning how the map scrolls';
    instruction = `Walk left and right on one floor · ${position?.calibration?.pairs ?? 0} of 20 samples. You can pause safely.`;
    action = 'Pause teaching'; run = () => command('teach_pause');
  } else if (phase === 'recording') {
    title = 'Teaching in progress';
    instruction = `${geometry?.platforms.length ?? 0} platforms learned. Finish to review the draft; the saved map will stay unchanged.`;
    action = 'Finish teaching'; run = () => command('teach_finish');
  } else if (phase === 'interrupted') {
    title = 'Teaching paused · draft recovered';
    instruction = 'Your saved samples are preserved. Resume only when you are ready; nothing restarted automatically.';
    action = 'Resume teaching'; run = () => command('teach_resume');
  } else if (phase === 'review') {
    title = missing.length ? 'Some journeys are missing from the recording' : 'Recorded paths connect';
    instruction = lost ? `Your position was unreadable in ${health?.misses} of ${health?.checks} checks. Keep this draft and report the tracking problem before repeating the walk.`
      : missing.length ? 'The missing connections are highlighted below. This does not mean the move is impossible.'
      : `${geometry?.platforms.length ?? 0} learned platforms. Review them before replacing the saved map.`;
    action = lost ? copied ? 'Report copied' : 'Copy tracking report' : missing.length ? 'Continue teaching' : 'Use this map';
    run = lost ? copyReport : missing.length ? () => command('teach_resume') : () => activate();
  }
  if (draft?.error) {
    title = phase === 'conflict' ? 'Draft needs recovery' : 'Recent changes could not be saved';
    instruction = draft.error;
    action = phase === 'conflict' ? 'Download preserved draft' : 'Retry saving draft';
    run = phase === 'conflict' ? async () => {
      const response = await fetch(`/api/v1/teaching-draft?area_id=${encodeURIComponent(position?.area_id ?? '')}`);
      if (!response.ok) throw new Error('The preserved draft could not be downloaded');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = 'teaching-draft.json'; link.click(); URL.revokeObjectURL(url);
    } : () => command('teach_checkpoint');
  }
  if (position && !phase && s.mode !== 'capture') {
    title = 'Stop the current run before teaching';
    instruction = 'Teaching sends no game keys. Stop the preview or combat run, then start teaching.';
    action = 'Stop run'; run = () => command('stop');
  }
  return <section className="teaching-panel" aria-label="Map teaching">
    <div className="teaching-summary">
      <span className="eyebrow">{position?.area_name ?? 'Map teaching'}</span><h3>{title}</h3><p>{instruction}</p>
      {!position && <label>Saved map<select aria-label="Saved map" value={mapId} onChange={event => setChosenArea(event.target.value)}><option value="">Choose a map…</option>{areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>}
      <div className="teaching-primary"><button className="primary" disabled={blocked || Boolean(confirmation) || discard || (lost && copied && !draft?.error)} onClick={() => void act(run)}>{action}</button>
        <span className={draft?.error ? 'draft-error' : 'draft-status'} role="status">{draft?.error ? 'Draft save needs attention' : draft?.pending ? 'Saving recent changes…' : draft?.saved && phase ? `Draft checkpoint saved · ${draft.saved_at ? new Date(draft.saved_at * 1000).toLocaleTimeString() : ''}` : phase ? 'Waiting for a saved checkpoint' : teaching?.map_receipt ? `Map revision ${teaching.map_receipt.revision} saved` : teaching?.map_revision ? `Saved map revision ${teaching.map_revision}` : ''}</span>
      </div>
      {position && <p className="saved-map-note">Saved map{teaching?.map_revision ? ` · revision ${teaching.map_revision}` : ''}{phase ? ' stays unchanged until you choose Use this map.' : ' is separate from a teaching draft.'}</p>}
      {s.capture_only && position?.supplement?.available && <div className="saved-map-note">
        <button aria-pressed={position.supplement.enabled}
          disabled={disabled || Boolean(phase) || s.mode !== 'capture' || Boolean(s.area_editing)}
          onClick={() => void command('position_supplement', { enabled: !position.supplement?.enabled })}>
          {position.supplement.enabled ? 'Stop observing middle ledge' : 'Observe middle ledge'}</button>
        <p>Session only · provisional screenshot coverage. The saved map and movement routes stay unchanged.</p>
      </div>}
      {confirmation && <div role="alertdialog" aria-label="Confirm map replacement" className="teaching-confirm"><h3>Replace the saved map?</h3>
        <p>{confirmation.platforms_before} saved platforms → {confirmation.platforms_after} learned platforms. Missing routes or removed places may make this map incomplete.{confirmation.zones_removed ? ` ${confirmation.zones_removed} zones outside the new boundary will be removed.` : ''} A backup of the previous map is retained.</p>
        <button disabled={disabled} className="primary" onClick={() => void activate(true)}>Replace with this draft</button><button onClick={() => setConfirmation(null)}>Keep reviewing</button></div>}
      {discard && <div role="alertdialog" aria-label="Confirm draft discard" className="teaching-confirm"><p>Discard this teaching draft? The saved map stays unchanged and a recovery copy is kept.</p><button disabled={disabled} onClick={() => void act(async () => { const result = await client.command('teach_cancel'); setDiscard(false); return result; })}>Discard teaching draft</button><button onClick={() => setDiscard(false)}>Keep draft</button></div>}
      {report && <label>Tracking report — copy this for repair<textarea readOnly rows={5} value={report} onFocus={event => event.target.select()} /></label>}
      {lost && copied && <p role="status">Tracking report copied. Keep this draft while the reader is investigated.</p>}
      {saveError && <p role="alert" className="draft-error">Map not replaced: {saveError}. Your teaching draft is kept.</p>}
    </div>
    {geometry && nodes.length > 0 && <>
      <label className="place-picker">Place<select value={place?.id ?? ''} onChange={event => setSelected(event.target.value)}>{nodes.map(item => <option key={item.id} value={item.id}>{placeName(item)} · {label(item.id)}</option>)}</select></label>
      <TeachingTerrain geometry={geometry} references={teaching?.references ?? []} selected={place} target={target} />
      {stranded && <p className="route-explanation">No return journey was recorded from <strong>{placeName(place)}</strong> to <strong>{placeName(home)}</strong>. The recording may have missed it.</p>}
      {unreachable && <p className="route-explanation">No journey was recorded from <strong>{placeName(home)}</strong> to <strong>{placeName(place)}</strong>.</p>}
      {missing.length > 0 && <div className="issue-places" aria-label="Places needing review">{missing.map(id => <button key={id} aria-pressed={place?.id === id} onClick={() => setSelected(id)}>{placeName(nodes.find(item => item.id === id))} · {label(id)}</button>)}</div>}
    </>}
    <details className="teaching-options"><summary>Other map actions</summary>
      {position && <label>Saved map<select value={mapId} onChange={event => setChosenArea(event.target.value)}><option value="">Choose a map…</option>{areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>}
      <div className="button-grid">{position && <button disabled={disabled || !mapId} onClick={() => void command('position_start', { area_id: mapId })}>Switch / reconnect map</button>}<button disabled={disabled || !position} onClick={() => void command('position_stop')}>Stop tracking</button></div>
      <label>Map name<input value={name} onChange={event => setName(event.target.value)} placeholder="e.g. Ant Tunnel" /></label>
      <button disabled={disabled} onClick={() => void act(async () => { const result = await client.command('teach_new_area', { name }); await refreshAreas(); return result; })}>Teach a new map</button>
      {phase && <div className="button-grid">{phase === 'review' && <><button disabled={disabled} onClick={() => void command('teach_resume')}>Continue teaching anyway</button><button disabled={disabled} onClick={() => void activate()}>Use this map…</button></>}
        {phase === 'recording' && <button disabled={disabled} onClick={() => void command('teach_pause')}>Pause teaching</button>}
        <button disabled={disabled} onClick={() => setDiscard(true)}>Discard draft…</button></div>}
    </details>
    <details className="teaching-options"><summary>Tracking evidence and calibration</summary>
      <p>{s.health?.reason ?? position?.reason ?? 'Track a map to see position status.'}</p>
      {health && <p>{health.misses} of {health.checks} position checks were unreadable.</p>}
      {(teaching?.evidence ?? []).map(file => <a className="evidence-link" key={file} href={`/api/v1/teaching-evidence?id=${encodeURIComponent(file)}`} target="_blank" rel="noreferrer"><img src={`/api/v1/teaching-evidence?id=${encodeURIComponent(file)}`} alt="Saved failed position reading" loading="lazy" />Open failed reading</a>)}
      {geometry && <>{problemText(geometry).map(line => <p key={line}>{line}</p>)}<MapSketch geometry={geometry} feet={position?.feet} /></>}
      <p>{position?.calibration?.saved ? `${position.calibration.saved.pairs} saved calibration samples` : 'Teaching calibrates the map automatically.'}</p>
      <button disabled={disabled || Boolean(phase)} onClick={() => void command('walk_calibration_begin')}>Recalibrate</button>
    </details>
  </section>;
}
