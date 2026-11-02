import { useEffect, useRef, useState } from 'react';
import type { EngineClient } from './client';
import type { AreaPoint, AreaProfile } from './contracts';
import './PathBuilder.css';

export interface FarmingRoute {
  version: 1; revision: number; id: string; name: string; area_id: string;
  map_hash: string; stops: string[]; loop: boolean;
  disabled_edges?: string[];
}
interface Leg { origin: string; target: string; edges: { id: string; kind: string; from: string; to: string; launch: number[]; landing: number[] }[] }
interface Validation { route: FarmingRoute; valid: boolean; errors: string[]; legs: Leg[]; connections?: Leg['edges'] }
interface Props {
  profile: AreaProfile; mapHash: string; client: EngineClient; disabled: boolean;
  onSelect?: (route: FarmingRoute | null) => void;
}

export function PathBuilder({ profile, mapHash, client, disabled, onSelect }: Props) {
  const fresh = (): FarmingRoute => ({ version: 1, revision: 0, id: crypto.randomUUID(), name: 'New farming circuit',
    area_id: profile.id, map_hash: mapHash, stops: [], loop: true });
  const draftKey = `maple-farming-draft:${profile.id}`;
  const [route, setRoute] = useState<FarmingRoute>(() => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(draftKey) ?? 'null');
      if (stored?.area_id === profile.id && Array.isArray(stored.stops)) return stored;
    } catch { /* A damaged browser draft never changes saved engine routes. */ }
    return fresh();
  });
  const [saved, setSaved] = useState<FarmingRoute[]>([]);
  const [history, setHistory] = useState<FarmingRoute[]>([]);
  const [future, setFuture] = useState<FarmingRoute[]>([]);
  const [dirty, setDirty] = useState(() => Boolean(sessionStorage.getItem(draftKey)));
  const [result, setResult] = useState<Validation | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [leg, setLeg] = useState(0);
  const [connections, setConnections] = useState<Leg['edges']>([]);
  const input = useRef<HTMLInputElement>(null);
  const epoch = useRef(0);
  const frozen = disabled || busy;
  useEffect(() => {
    try {
      if (dirty) sessionStorage.setItem(draftKey, JSON.stringify(route));
      else sessionStorage.removeItem(draftKey);
    } catch { /* The in-memory draft and explicit JSON export remain available. */ }
  }, [route, dirty, draftKey]);
  useEffect(() => {
    let current = true;
    void client.command<{ routes: FarmingRoute[] }>('farm_route_list', { area_id: profile.id })
      .then(value => { if (current) setSaved(value.routes ?? []); })
      .catch(error => { if (current) setMessage(String(error)); });
    return () => { current = false; epoch.current++; };
  }, [profile.id, client]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const change = (next: FarmingRoute) => {
    epoch.current++; onSelect?.(null); setResult(null); setMessage('');
    setHistory([...history.slice(-49), route]); setFuture([]); setRoute(next); setDirty(true);
  };
  const replace = (next: FarmingRoute) => {
    if (dirty && !window.confirm('Discard unsaved circuit changes?')) return false;
    epoch.current++; onSelect?.(null); setRoute(next); setHistory([]); setFuture([]);
    setDirty(false); setResult(null); setMessage('');
    return true;
  };
  const run = async (operation: () => Promise<void>) => {
    setBusy(true); setMessage('');
    try { await operation(); } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const validate = async () => {
    const current = epoch.current;
    const value = await client.command<Validation>('farm_route_validate', { route });
    if (current === epoch.current) { setResult(value); setConnections(value.connections ?? []); }
  };
  const save = async () => {
    const value = await client.command<{ route: FarmingRoute }>('farm_route_save', { route });
    setRoute(value.route); setDirty(false); setResult(null); onSelect?.(null);
    setSaved(previous => [...previous.filter(item => item.id !== value.route.id), value.route]);
    setMessage('Circuit saved. Validate it before selecting it for farming.');
  };
  const move = (index: number, delta: number) => {
    const stops = [...route.stops];
    [stops[index], stops[index + delta]] = [stops[index + delta], stops[index]];
    change({ ...route, stops });
  };
  const box = profile.boundary;
  const centers = new Map(profile.platforms.map(p => [p.id, { x: (p.start.x + p.end.x) / 2, y: (p.start.y + p.end.y) / 2 }]));
  const names = new Map(profile.platforms.map(p => [p.id, p.name || p.id]));
  const pairs = route.stops.slice(1).map((target, index) => [route.stops[index], target]);
  if (route.loop && route.stops.length > 1) pairs.push([route.stops.at(-1)!, route.stops[0]]);
  return <section className="path-builder" aria-label="Farming path builder">
    <div className="path-heading"><div><h3>Build your farming circuit</h3><p>Choose platforms in the order you want to farm them. Connecting moves use the current navigation limits.</p></div>
      <span>{dirty ? 'Unsaved changes' : `Revision ${route.revision}`}</span></div>
    <fieldset disabled={frozen}>
      <div className="path-toolbar">
        <label>Saved circuit <select value={saved.some(item => item.id === route.id) ? route.id : ''} onChange={event => { const found = saved.find(item => item.id === event.target.value); if (found) replace(found); }}>
          <option value="">Choose a saved circuit</option>{saved.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <button onClick={() => replace(fresh())}>New circuit</button>
        <button onClick={() => change({ ...route, id: crypto.randomUUID(), revision: 0, name: `${route.name} copy` })}>Duplicate</button>
        <button disabled={!history.length} onClick={() => { epoch.current++; onSelect?.(null); setFuture([route, ...future]); setRoute(history.at(-1)!); setHistory(history.slice(0, -1)); setDirty(true); setResult(null); }}>Undo</button>
        <button disabled={!future.length} onClick={() => { epoch.current++; onSelect?.(null); setHistory([...history, route]); setRoute(future[0]); setFuture(future.slice(1)); setDirty(true); setResult(null); }}>Redo</button>
      </div>
      <div className="path-workspace">
        <div><div className="path-toolbar"><label>Zoom <input aria-label="Circuit zoom" type="range" min="1" max="4" step="0.25" value={zoom} onChange={event => setZoom(Number(event.target.value))} /></label>
          <button onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>Fit map</button>
          <span>Drag empty map space to pan</span></div>
          <svg className="path-canvas" role="img" aria-label="Farming circuit map" viewBox={`${box.x + pan.x} ${box.y + pan.y} ${box.width / zoom} ${box.height / zoom}`}
            onPointerDown={event => { if (event.target === event.currentTarget) event.currentTarget.setPointerCapture?.(event.pointerId); }}
            onPointerMove={event => { if (event.currentTarget.hasPointerCapture?.(event.pointerId)) { const rect = event.currentTarget.getBoundingClientRect(); setPan(p => ({ x: p.x - event.movementX * box.width / zoom / rect.width, y: p.y - event.movementY * box.height / zoom / rect.height })); } }}
            onPointerUp={event => { if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}>
            {profile.zones.map(zone => <rect key={zone.id} className="path-zone" x={zone.rect.x} y={zone.rect.y} width={zone.rect.width} height={zone.rect.height} />)}
            {profile.ropes.map(p => <line key={p.id} className="path-rope" x1={p.start.x} y1={p.start.y} x2={p.end.x} y2={p.end.y} />)}
            {pairs.map(([from, to], index) => { const a = centers.get(from), b = centers.get(to); return a && b ? <g key={index} className={index === leg ? 'path-leg selected' : 'path-leg'}><line x1={a.x} y1={a.y - 12} x2={b.x} y2={b.y - 12} /><text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 20}>{index + 1} →</text></g> : null; })}
            {profile.platforms.map(p => <g key={p.id} className="path-platform" onClick={() => { if (!frozen) change({ ...route, stops: [...route.stops, p.id] }); }}>
              <polyline points={((p as typeof p & { points?: AreaPoint[] }).points ?? [p.start, p.end]).map(point => `${point.x},${point.y}`).join(' ')} /><title>{names.get(p.id)}: add farming stop</title>
              {route.stops.map((id, index) => id === p.id ? <text key={index} x={centers.get(id)!.x + index * 12} y={centers.get(id)!.y - 18}>{index + 1}</text> : null)}
            </g>)}
          </svg>
          <label>Add a platform <select value="" onChange={event => change({ ...route, stops: [...route.stops, event.target.value] })}><option value="">Choose a farming stop</option>{profile.platforms.map(p => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}</select></label>
        </div>
        <div className="path-stops"><label>Circuit name <input maxLength={100} value={route.name} onChange={event => change({ ...route, name: event.target.value })} /></label>
          <ol aria-label="Farming stops">{route.stops.map((id, index) => <li key={index}><strong>{names.get(id) ?? `${id} (missing)`}</strong><div>
            <button aria-label={`Move stop ${index + 1} up`} disabled={index === 0} onClick={() => move(index, -1)}>↑</button>
            <button aria-label={`Move stop ${index + 1} down`} disabled={index === route.stops.length - 1} onClick={() => move(index, 1)}>↓</button>
            <button aria-label={`Remove stop ${index + 1}`} onClick={() => change({ ...route, stops: route.stops.filter((_, i) => i !== index) })}>Remove</button></div></li>)}</ol>
          {!route.stops.length && <p>Add at least two platforms to begin.</p>}
          <label><input type="checkbox" checked={route.loop} onChange={event => change({ ...route, loop: event.target.checked })} /> Return to the first stop and repeat</label>
          <p>Each stop is farmed until clear. Intermediate platforms are used for travel.</p>
          {pairs.length > 0 && <label>Inspect connection <select value={leg} onChange={event => setLeg(Number(event.target.value))}>{pairs.map(([a, b], index) => <option key={index} value={index}>{index + 1}: {names.get(a) ?? a} → {names.get(b) ?? b}</option>)}</select></label>}
          {result?.legs[leg] && <ol aria-label="Connection movements">{result.legs[leg].edges.map(edge => <li key={edge.id}>{edge.kind}: {edge.from} → {edge.to}<small>Launch {edge.launch.join(', ')}; land {edge.landing.join(', ')}</small></li>)}</ol>}
          {connections.length > 0 && <details><summary>Edit directed movement connections</summary><p>Allow or exclude computed moves, then validate the circuit again.</p>
            {connections.map(edge => <label key={edge.id}><input type="checkbox" checked={!route.disabled_edges?.includes(edge.id)} onChange={event => change({ ...route, disabled_edges: event.target.checked ? (route.disabled_edges ?? []).filter(id => id !== edge.id) : [...(route.disabled_edges ?? []), edge.id] })} />{edge.kind}: {edge.from} → {edge.to}<small>Launch {edge.launch.join(', ')}; land {edge.landing.join(', ')}</small></label>)}</details>}
        </div>
      </div>
      <div className="path-toolbar"><button disabled={!dirty || route.stops.length < 2} onClick={() => void run(save)}>Save circuit</button>
        <button disabled={route.stops.length < 2} onClick={() => void run(validate)}>Validate circuit</button>
        <button disabled={dirty || !result?.valid || route.revision === 0} onClick={() => { onSelect?.(route); setMessage('Selected for farming. Choose Farming in the header and start the displayed bounded session.'); }}>Use for farming</button>
        <button onClick={() => { const blob = new Blob([JSON.stringify(route, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `${route.id}.json`; a.click(); URL.revokeObjectURL(url); }}>Export JSON</button>
        <button onClick={() => input.current?.click()}>Import JSON</button>
        <input ref={input} hidden type="file" accept="application/json,.json" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (!file) return; void run(async () => { if (file.size > 64000) throw new Error('Route file is too large'); const value = JSON.parse(await file.text()) as FarmingRoute; if (value.version !== 1 || !Array.isArray(value.stops) || value.stops.some(id => typeof id !== 'string')) throw new Error('Unsupported route file'); if (replace({ ...value, id: crypto.randomUUID(), revision: 0 })) setDirty(true); }); }} />
        {route.map_hash !== mapHash && <button onClick={() => change({ ...route, area_id: profile.id, map_hash: mapHash })}>Bind draft to current map</button>}
      </div>
    </fieldset>
    {result && <div role="status">{result.valid ? `${result.legs.length} connections ready within current movement limits.` : <ul>{result.errors.map((error, index) => <li key={index}>{error}</li>)}</ul>}</div>}
    {message && <p role="status">{message}</p>}
  </section>;
}

