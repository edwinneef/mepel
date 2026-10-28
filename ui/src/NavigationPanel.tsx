import { useState } from 'react';
import type { Snapshot } from './contracts';
import type { EngineClient } from './client';

interface Props {
  snapshot: Snapshot; client: EngineClient; disabled: boolean;
  act: (operation: () => Promise<unknown>) => Promise<void>;
  onPreview: () => void; onInvalidate: () => void;
  supervised: boolean; onSupervised: (value: boolean) => void;
  areas?: { id: string; name: string }[];
}

export function NavigationPanel({ snapshot: s, client, disabled, act, onPreview, onInvalidate,
  supervised, onSupervised, areas = [] }: Props) {
  const [origin, setOrigin] = useState('');
  const [chosenMap, setChosenMap] = useState('');
  const [target, setTarget] = useState('');
  const nav = s.navigation;
  const map = s.position && s.position.area_id !== nav?.map?.area_id ? null : nav?.map;
  const route = nav?.route;
  const from = origin || (nav?.active ? route?.origin : '') || (s.position?.surface_id && map?.nodes.some(n => n.id === s.position?.surface_id && !n.excluded)
    ? s.position.surface_id : map?.home ?? '');
  const name = (id: string) => {
    const label = map?.nodes.find(n => n.id === id)?.name ?? id;
    const stableId = id.replace('walk_', '').toUpperCase();
    return label.endsWith(` · ${stableId}`) ? label : `${label} · ${stableId}`;
  };
  const frozen = disabled || Boolean(nav?.active);
  const previewed = route?.origin === from && route?.target === target;
  const load = () => act(async () => { onInvalidate(); return client.command('nav_refresh'); });
  const preview = () => act(async () => {
    onInvalidate();
    const result = await client.command('nav_preview', { origin: from, target });
    onPreview(); return result;
  });
  return <section className="route-panel" aria-label="Bounded navigation">
    <span className="eyebrow">Navigation · no combat</span>
    <h3>{nav?.active ? `Moving to ${name(route?.target ?? '')}` : nav?.stage === 'arrived'
      ? 'Destination reached' : previewed ? 'Route preview ready' : 'Choose a destination'}</h3>
    <p>{nav?.active || nav?.stage === 'stopped' || nav?.stage === 'arrived' ? nav.reason
      : 'Preview recorded paths first. Movement starts only from the header after explicit supervision.'}</p>
    {nav?.active && <p>Move {Math.min((nav.edge_index ?? 0) + 1, route?.edges.length ?? 0)} of {route?.edges.length ?? 0} · {nav.stage.replaceAll('_', ' ')} · {nav.completed ?? 0} completed</p>}
    {!map ? s.position ? <><p>Load routes for {s.position.area_name ?? 'the tracked map'}.</p>
      <button className="primary" disabled={disabled} onClick={() => void load()}>Load navigation routes</button></>
      : <><label>Saved map<select aria-label="Map to track" value={chosenMap} disabled={disabled}
          onChange={e => setChosenMap(e.target.value)}><option value="">Choose a map…</option>
          {areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label>
        <button className="primary" disabled={disabled || !chosenMap} onClick={() => void act(async () => {
          await client.command('position_start', { area_id: chosenMap });
          return client.command('nav_refresh');
        })}>Track map and load routes</button></>
      : <>
        <label>Preview origin<select aria-label="Route origin" value={from} disabled={frozen}
          onChange={e => { setOrigin(e.target.value); onInvalidate(); }}>
          {map.nodes.filter(n => n.kind === 'platform').map(n => <option key={n.id} value={n.id} disabled={n.excluded}>{name(n.id)}{n.excluded ? ' · unavailable' : ''}</option>)}
        </select></label>
        {/* Always reserve the line: the live position changes several times a second. */}
        <p className="route-preview-note" style={{ visibility: s.position?.kind !== 'platform' || s.position.surface_id !== from ? 'visible' : 'hidden' }}>
          Hypothetical origin for preview. Start requires your fresh position on {name(from)}.</p>
        <label>Destination<select aria-label="Route destination" value={target} disabled={frozen}
          onChange={e => { setTarget(e.target.value); onInvalidate(); }}>
          <option value="">Choose a reachable platform</option>
          {map.nodes.filter(n => n.kind === 'platform').map(n => <option key={n.id} value={n.id} disabled={n.excluded}>{name(n.id)}{n.excluded ? ' · unavailable' : ''}</option>)}
        </select></label>
        <button className="primary" disabled={frozen || !target} onClick={() => void preview()}>Preview route</button>
        {previewed && <div className="route-preview" aria-label="Recorded route preview">
          <p><strong>{name(route.origin)} → {name(route.target)}</strong></p>
          {route.edges.length ? <ol>{route.edges.map(edge => <li key={edge.id}>{edge.kind} · {name(edge.source)} → {name(edge.target)}</li>)}</ol>
            : <p>Already on the destination platform; no movement edges needed.</p>}
          <p>Up to 8 moves · 60 seconds total · 8 seconds per move. Lost position or focus releases movement keys.</p>
          {!s.capture_only && <label className="supervision-check"><input type="checkbox" checked={supervised}
            disabled={frozen} onChange={e => onSupervised(e.target.checked)} /> I will supervise this bounded route</label>}
          <p className="warning-copy">{nav?.blocker ?? 'Choose Navigation in the header and use Start navigation when ready.'}</p>
        </div>}
        <details><summary>Unavailable places and route limits</summary>
          <ul>{map.nodes.filter(n => n.excluded).map(n => <li key={n.id}>{n.name} · {n.id.replace('walk_', '').toUpperCase()}: no evidenced safe round trip</li>)}</ul>
          <p>{map.usable_edges} evidenced movement links. Arrival and rope grip are inferred from fresh movement feedback; native acceptance remains separate.</p>
          <button disabled={frozen} onClick={() => void load()}>Reload route evidence</button>
        </details>
      </>}
  </section>;
}
