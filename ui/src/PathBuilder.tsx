import { useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import type { EngineClient } from './client';
import type { AreaPoint, AreaProfile } from './contracts';
import { center, legPaths, legText, loopOrder, planRoute, platformAt, shortestOrder, suggestions, usableMoves } from './pathPlanning';
import type { PlannedLeg, RouteOptions } from './pathPlanning';
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
  /** Farmable platforms and trusted moves from `farm_route_map`; older engines omit them. */
  options?: RouteOptions;
  onSelect?: (route: FarmingRoute | null) => void;
  /** Live player feet in map pixels; faded while the reading is briefly stale. */
  player?: { feet: [number, number]; stale: boolean } | null;
}
type Platform = AreaProfile['platforms'][number] & { points?: AreaPoint[] };
const DEFAULT_NAME = 'New farming circuit';

/** One leg drawn as the bot travels it, or a red dashed line when no trusted move exists. */
function LegDrawing({ leg, index, centers, selected }: { leg: PlannedLeg; index: number; centers: Map<string, { x: number; y: number }>; selected: boolean }) {
  if (!leg.moves) {
    const a = centers.get(leg.origin), b = centers.get(leg.target);
    if (!a || !b) return null;
    return <g className="path-leg blocked"><line x1={a.x} y1={a.y - 12} x2={b.x} y2={b.y - 12} />
      <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 20}>✕ {index + 1}</text></g>;
  }
  const { walks, hops } = legPaths(leg);
  const middle = leg.moves[Math.floor(leg.moves.length / 2)];
  return <g className={selected ? 'path-leg selected' : 'path-leg'}>
    {walks.map((d, i) => <path key={`w${i}`} className="path-walk" d={d} />)}
    {hops.map((d, i) => <path key={`h${i}`} d={d} markerEnd={i === hops.length - 1 ? 'url(#path-arrow)' : undefined} />)}
    {middle && <text x={(middle.launch[0] + middle.landing[0]) / 2 + 8} y={Math.min(middle.launch[1], middle.landing[1]) - 34}>{index + 1}</text>}
  </g>;
}

export function PathBuilder({ profile, mapHash, client, disabled, options, onSelect, player }: Props) {
  const fresh = (): FarmingRoute => ({ version: 1, revision: 0, id: crypto.randomUUID(), name: DEFAULT_NAME,
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
  const [hint, setHint] = useState('');
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [leg, setLeg] = useState(0);
  const [auto, setAuto] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const [connections, setConnections] = useState<Leg['edges']>([]);
  const [filter, setFilter] = useState('');
  const [sketch, setSketch] = useState<{ seq: string[]; trail: { x: number; y: number }[] } | null>(null);
  const gesture = useRef<{ x: number; y: number; moved: boolean; panning: boolean; seq: string[]; trail: { x: number; y: number }[] } | null>(null);
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
    setDirty(false); setResult(null); setMessage(''); setHint(''); setAuto(false); setSource(null);
    return true;
  };
  const run = async (operation: () => Promise<void>) => {
    setBusy(true); setMessage('');
    try { await operation(); } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const save = async () => {
    const checked = await client.command<Validation>('farm_route_validate', { route });
    setResult(checked); setConnections(checked.connections ?? []);
    if (!checked.valid) { setMessage('Fix the connection problems below, then check this path again.'); return; }
    const value = dirty || route.revision === 0
      ? await client.command<{ route: FarmingRoute }>('farm_route_save', { route }) : { route };
    setRoute(value.route); setDirty(false); setResult(null); onSelect?.(null);
    setSaved(previous => [...previous.filter(item => item.id !== value.route.id), value.route]);
    setResult({ ...checked, route: value.route });
    setMessage('Path checked and saved. Select it for farming when you are ready.');
  };

  const platforms = profile.platforms as Platform[];
  const names = new Map(platforms.map(p => [p.id, p.name || p.id]));
  const centers = new Map(platforms.map(p => [p.id, center(p)]));
  const farmable = options?.farmable ? new Set(options.farmable) : null;
  const canFarm = (id: string) => !farmable || farmable.has(id);
  const moves = usableMoves(options ?? {}, route.disabled_edges);
  const hasMoves = Boolean(options?.moves?.length);
  const legs: PlannedLeg[] = hasMoves ? planRoute(profile, moves, route.stops, route.loop)
    : route.stops.slice(1).map((target, i) => [route.stops[i], target]).concat(route.loop && route.stops.length > 1 ? [[route.stops.at(-1)!, route.stops[0]]] : [])
      .map(([origin, target]) => ({ origin, target, moves: [], start: [0, 0], end: [0, 0] }));
  const blockedLeg = hasMoves ? legs.findIndex(item => !item.moves) : -1;
  // Suggestions plan many trips; compute once per map rather than on every pointer move.
  const ideas = useMemo(() => hasMoves ? suggestions(profile, options ?? {}) : [], [hasMoves, profile, options]);

  const automatic = (stops: string[]) => (route.loop ? loopOrder(profile, moves, stops) : null) ?? shortestOrder(profile, moves, stops);
  const ordered = (stops: string[]) => auto && hasMoves ? automatic(stops) : stops;
  const toggle = (id: string) => {
    if (frozen) return;
    if (!canFarm(id)) { setHint(`${names.get(id) ?? id} can't be a farming stop: the bot has no trusted way there and back.`); return; }
    setHint('');
    const stops = route.stops.includes(id) ? route.stops.filter(stop => stop !== id) : ordered([...route.stops, id]);
    change({ ...route, stops });
  };
  const pick = (id: string) => {
    const idea = ideas.find(item => item.id === id);
    if (!idea || frozen) return;
    setAuto(true); setSource(id); setHint('');
    change({ ...route, stops: idea.stops, name: route.name === DEFAULT_NAME || ideas.some(item => item.name === route.name) ? idea.name : route.name });
  };
  const move = (index: number, delta: number) => {
    const stops = [...route.stops];
    [stops[index], stops[index + delta]] = [stops[index + delta], stops[index]];
    setAuto(false); change({ ...route, stops });
  };

  // Map pointer: a press that moves draws the stop order; a press that stays put toggles a
  // platform; Shift or the middle button pans when zoomed in.
  const box = profile.boundary;
  const view = { x: box.x + pan.x, y: box.y + pan.y, width: box.width / zoom, height: box.height / zoom };
  const toMap = (event: ReactPointerEvent<SVGSVGElement>) => {
    const svg = event.currentTarget;
    const matrix = svg.getScreenCTM?.();
    if (matrix && svg.createSVGPoint) {
      const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
      const mapped = point.matrixTransform(matrix.inverse());
      return { x: mapped.x, y: mapped.y };
    }
    const rect = svg.getBoundingClientRect();
    return { x: view.x + (event.clientX - rect.left) * view.width / (rect.width || 1), y: view.y + (event.clientY - rect.top) * view.height / (rect.height || 1) };
  };
  const reach = Math.max(view.width, view.height) * 0.03;
  const down = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (frozen || (event.button !== 0 && event.button !== 1)) return;
    const point = toMap(event), hit = platformAt(profile, point, reach);
    gesture.current = { x: event.clientX, y: event.clientY, moved: false, panning: event.shiftKey || event.button === 1, seq: hit ? [hit] : [], trail: [point] };
    event.preventDefault();
    // Capture keeps a fast sweep drawing past the map edge; a pointer the browser no longer
    // tracks throws, which must not cancel the gesture.
    try { event.currentTarget.setPointerCapture?.(event.pointerId); } catch { /* drawing still works inside the map */ }
  };
  const moveGesture = (event: ReactPointerEvent<SVGSVGElement>) => {
    const current = gesture.current;
    if (!current) return;
    if (!current.moved && Math.hypot(event.clientX - current.x, event.clientY - current.y) < 8) return;
    current.moved = true;
    if (current.panning) {
      const rect = event.currentTarget.getBoundingClientRect();
      setPan(p => ({ x: p.x - event.movementX * view.width / (rect.width || 1), y: p.y - event.movementY * view.height / (rect.height || 1) }));
      return;
    }
    const point = toMap(event), hit = platformAt(profile, point, reach);
    current.trail.push(point);
    if (hit && current.seq.at(-1) !== hit) current.seq.push(hit);
    setSketch({ seq: [...current.seq], trail: [...current.trail] });
  };
  const up = (event: ReactPointerEvent<SVGSVGElement>) => {
    const current = gesture.current;
    gesture.current = null; setSketch(null);
    try { if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); } catch { /* already released */ }
    if (!current || current.panning) return;
    if (!current.moved) { if (current.seq[0]) toggle(current.seq[0]); return; }
    const unique = [...new Set(current.seq)], kept = unique.filter(canFarm), skipped = unique.filter(id => !canFarm(id));
    if (!kept.length) return;
    setAuto(false); setSource('draw');
    setHint(`Using the order you drew (${kept.length} ${kept.length === 1 ? 'stop' : 'stops'}).`
      + (skipped.length ? ` Skipped ${skipped.map(id => names.get(id) ?? id).join(', ')}: no trusted way there and back.` : '')
      + (current.seq.length > unique.length ? ' A platform crossed twice counts once.' : ''));
    change({ ...route, stops: kept });
  };
  const shown = sketch?.seq ?? route.stops;
  const shownLegs = sketch ? (hasMoves ? planRoute(profile, moves, sketch.seq, false) : []) : legs;
  const badgeAt = (index: number) => {
    const id = shown[index], c = centers.get(id);
    if (!c) return null;
    const arrived = index === 0 ? (route.loop && !sketch && shownLegs.at(-1)?.target === id ? shownLegs.at(-1) : null) : shownLegs[index - 1];
    return arrived?.moves?.length ? { x: arrived.end[0], y: arrived.end[1] } : c;
  };
  const status = route.stops.length < 2
    ? (ideas.length ? 'Pick a starting point above, or drag across the map to draw your own path.' : 'Drag across the map to draw your path, or click platforms to switch them on.')
    : blockedLeg >= 0 ? `Trip ${blockedLeg + 1} (${names.get(legs[blockedLeg].origin)} → ${names.get(legs[blockedLeg].target)}) has no trusted move. Change the order or switch a stop off.`
      : dirty || !result?.valid ? `${route.stops.length} stops${hasMoves ? ', and every trip has a trusted move' : ''}. Next: check and save your path.`
        : 'Your path is ready. Select it for farming below.';
  // Card thumbnails plan whole loops; build them once per set of suggestions.
  const sketches = useMemo(() => ideas.map(idea => {
    const planned = planRoute(profile, usableMoves(options ?? {}), idea.stops, true);
    return <svg viewBox={`${profile.boundary.x} ${profile.boundary.y} ${profile.boundary.width} ${profile.boundary.height}`} aria-hidden="true" className="path-sketch">
      {(profile.platforms as Platform[]).map(p => <polyline key={p.id} className={idea.stops.includes(p.id) ? 'on' : ''} points={(p.points ?? [p.start, p.end]).map(point => `${point.x},${point.y}`).join(' ')} />)}
      {planned.map((item, i) => { const { walks, hops } = legPaths(item); return <g key={i}>{[...walks, ...hops].map((d, j) => <path key={j} d={d} />)}</g>; })}
    </svg>;
  }), [ideas, profile, options]);

  return <section className="path-builder" aria-label="Farming path builder">
    <div className="path-heading"><div><h3>2. Build your path</h3><p>Start from a ready-made path or draw your own. Then switch stops on or off. The bot fights on each stop until no enemies remain, then travels to the next.</p></div>
      <span>{dirty ? 'Unsaved changes' : `Revision ${route.revision}`}</span></div>
    <fieldset disabled={frozen}>
      <details><summary>Saved paths and editing tools</summary><div className="path-toolbar">
        <label>Saved path <select value={saved.some(item => item.id === route.id) ? route.id : ''} onChange={event => { const found = saved.find(item => item.id === event.target.value); if (found) replace(found); }}>
          <option value="">Choose a saved path</option>{saved.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <button onClick={() => replace(fresh())}>New path</button>
        <button onClick={() => change({ ...route, id: crypto.randomUUID(), revision: 0, name: `${route.name} copy` })}>Duplicate</button>
      </div></details>
      {ideas.length > 0 && <><span className="path-eyebrow">Start from</span>
        <div className="path-ideas">{ideas.map((idea, index) => <button key={idea.id} className="path-idea" aria-pressed={source === idea.id} onClick={() => pick(idea.id)}>
          {sketches[index]}<strong>{idea.name}</strong><small>{idea.why} · {idea.stops.length} stops</small></button>)}
          <button className="path-idea" aria-pressed={source === 'draw'} onClick={() => { setSource('draw'); setHint('Hold the mouse down on the map and sweep across platforms in the order you want.'); }}>
            <span className="path-idea-draw" aria-hidden="true">✎</span><strong>Draw your own</strong><small>Hold the mouse and sweep across platforms in order.</small></button></div></>}
      <p className={`path-next ${blockedLeg >= 0 ? 'bad' : ''}`} role="status">{hint ? `${hint} ` : ''}{status}</p>
      <div className="path-workspace">
        <div><div className="path-mapbox"><div className="path-toolbar path-map-tools"><label>Zoom <input aria-label="Circuit zoom" type="range" min="1" max="4" step="0.25" value={zoom} onChange={event => setZoom(Number(event.target.value))} /></label>
          <button onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>Fit map</button>
          <button disabled={!history.length} onClick={() => { epoch.current++; onSelect?.(null); setFuture([route, ...future]); setRoute(history.at(-1)!); setHistory(history.slice(0, -1)); setDirty(true); setResult(null); setHint(''); }}>Undo</button>
          <button disabled={!future.length} onClick={() => { epoch.current++; onSelect?.(null); setHistory([...history, route]); setRoute(future[0]); setFuture(future.slice(1)); setDirty(true); setResult(null); setHint(''); }}>Redo</button>
          <button disabled={!route.stops.length} onClick={() => { setHint(''); change({ ...route, stops: [] }); }}>Clear stops</button></div>
          <svg className={`path-canvas ${sketch ? 'drawing' : ''}`} role="img" aria-label="Farming circuit map: drag across platforms to draw the order, click a platform to switch it on or off"
            viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`} onPointerDown={down} onPointerMove={moveGesture} onPointerUp={up} onPointerCancel={up}>
            <defs><marker id="path-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10z" /></marker></defs>
            {profile.zones.map(zone => <rect key={zone.id} className="path-zone" x={zone.rect.x} y={zone.rect.y} width={zone.rect.width} height={zone.rect.height} />)}
            {profile.ropes.map(p => <line key={p.id} className="path-rope" x1={p.start.x} y1={p.start.y} x2={p.end.x} y2={p.end.y} />)}
            {platforms.map(p => <g key={p.id} data-platform={p.id} className={['path-platform', shown.includes(p.id) ? 'on' : '', !canFarm(p.id) ? 'blocked' : ''].join(' ')}>
              <polyline points={(p.points ?? [p.start, p.end]).map(point => `${point.x},${point.y}`).join(' ')} />
              <title>{names.get(p.id)}{canFarm(p.id) ? '' : ' (no trusted way there and back)'}</title>
              <text className="path-name" x={Math.min(p.start.x, p.end.x) + 4} y={Math.max(p.start.y, p.end.y) + 22}>{names.get(p.id)}</text></g>)}
            {shownLegs.map((item, index) => <LegDrawing key={index} leg={item} index={index} centers={centers} selected={index === leg && !sketch} />)}
            {shown.map((id, index) => { const at = badgeAt(index); return at ? <g key={index} className="path-badge"><circle cx={at.x} cy={at.y - 30} r={14} /><text x={at.x} y={at.y - 30}>{index + 1}</text></g> : null; })}
            {player && <circle className={player.stale ? 'path-player stale' : 'path-player'} cx={player.feet[0]} cy={player.feet[1] - 10} r={10}><title>You</title></circle>}
            {sketch && <polyline className="path-trail" points={sketch.trail.map(point => `${point.x},${point.y}`).join(' ')} />}
          </svg></div>
          <p className="path-legend"><span><b>Drag</b> across platforms to draw the order</span><span><b>Click</b> a platform to switch it on or off</span><span><b>Shift+drag</b> pans when zoomed</span></p>
        </div>
        <div className="path-stops"><label>Path name <input maxLength={100} value={route.name} onChange={event => change({ ...route, name: event.target.value })} /></label>
          <div className="path-chips-head"><span>Platforms <small>{route.stops.length} stops · {platforms.filter(p => canFarm(p.id)).length} farmable</small></span>
            {platforms.length > 12 && <input type="search" aria-label="Find a platform" placeholder="Find…" value={filter} onChange={event => setFilter(event.target.value)} />}</div>
          {/* Compact chips scale to maps with dozens of platforms; natural order reads Level 3 … 24. */}
          <div role="group" aria-label="Farming platforms" className="path-chips">{[...platforms]
            .sort((a, b) => (names.get(a.id) ?? '').localeCompare(names.get(b.id) ?? '', undefined, { numeric: true }))
            .filter(p => !filter || (names.get(p.id) ?? '').toLowerCase().includes(filter.toLowerCase()))
            .map(p => { const stop = route.stops.indexOf(p.id); return <label key={p.id} className={['path-chip', stop >= 0 ? 'on' : '', canFarm(p.id) ? '' : 'blocked'].join(' ')}
              title={!canFarm(p.id) ? 'No trusted way there and back' : stop >= 0 ? `Stop ${stop + 1}` : 'Travel only: click to farm here'}>
              <input type="checkbox" role="switch" aria-label={`Farm on ${names.get(p.id)}`} checked={stop >= 0} disabled={!canFarm(p.id)} onChange={() => toggle(p.id)} />
              {stop >= 0 && <b aria-hidden="true">{stop + 1}</b>}<span>{names.get(p.id)}</span></label>; })}</div>
          {hasMoves && <label><input type="checkbox" checked={auto} onChange={event => { setAuto(event.target.checked); if (event.target.checked && route.stops.length > 2) change({ ...route, stops: automatic(route.stops) }); }} /> Let the bot choose the order</label>}
          {(!auto || !hasMoves) && route.stops.length > 0 && <ol aria-label="Farming stops">{route.stops.map((id, index) => <li key={index}><strong>{names.get(id) ?? `${id} (missing)`}</strong><div>
            <button aria-label={`Move stop ${index + 1} up`} disabled={index === 0} onClick={() => move(index, -1)}>↑</button>
            <button aria-label={`Move stop ${index + 1} down`} disabled={index === route.stops.length - 1} onClick={() => move(index, 1)}>↓</button>
            <button aria-label={`Remove stop ${index + 1}`} onClick={() => change({ ...route, stops: route.stops.filter((_, i) => i !== index) })}>Remove</button></div></li>)}</ol>}
          <label><input type="checkbox" checked={route.loop} onChange={event => change({ ...route, loop: event.target.checked })} /> Return to the first stop and repeat</label>
          {hasMoves && legs.length > 0 && <details open={blockedLeg >= 0}><summary>How the bot travels ({legs.length} {legs.length === 1 ? 'trip' : 'trips'})</summary>
            <ol className="path-trips" aria-label="Trips">{legs.map((item, index) => <li key={index} className={item.moves ? '' : 'bad'}>
              <strong>{item.moves ? '✓' : '✕'} {names.get(item.origin)} → {names.get(item.target)}</strong><small>{legText(item, names)}</small></li>)}</ol></details>}
          <details><summary>Advanced movement details</summary>{legs.length > 0 && <label>Inspect connection <select value={leg} onChange={event => setLeg(Number(event.target.value))}>{legs.map((item, index) => <option key={index} value={index}>{index + 1}: {names.get(item.origin) ?? item.origin} → {names.get(item.target) ?? item.target}</option>)}</select></label>}
          {result?.legs[leg] && <ol aria-label="Connection movements">{result.legs[leg].edges.map(edge => <li key={edge.id}>{edge.kind}: {edge.from} → {edge.to}<small>Launch {edge.launch.join(', ')}; land {edge.landing.join(', ')}</small></li>)}</ol>}
          {connections.length > 0 && <details><summary>Edit directed movement connections</summary><p>Allow or exclude computed moves, then validate the circuit again.</p>
            {connections.map(edge => <label key={edge.id}><input type="checkbox" checked={!route.disabled_edges?.includes(edge.id)} onChange={event => change({ ...route, disabled_edges: event.target.checked ? (route.disabled_edges ?? []).filter(id => id !== edge.id) : [...(route.disabled_edges ?? []), edge.id] })} />{edge.kind}: {edge.from} → {edge.to}<small>Launch {edge.launch.join(', ')}; land {edge.landing.join(', ')}</small></label>)}</details>}
        </details></div>
      </div>
      <h3>3. Check and save</h3><div className="path-toolbar"><button className="primary" disabled={route.stops.length < 2} onClick={() => void run(save)}>Check and save path</button>
        <button disabled={dirty || !result?.valid || route.revision === 0} onClick={() => { onSelect?.(route); setMessage('Selected for farming. Review the selected activity and session limits before using the normal Start or On control.'); }}>Select for farming</button>
        <details><summary>Import or export a path</summary><button onClick={() => { const blob = new Blob([JSON.stringify(route, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `${route.id}.json`; a.click(); URL.revokeObjectURL(url); }}>Export JSON</button>
        <button onClick={() => input.current?.click()}>Import JSON</button>
        <input ref={input} hidden type="file" accept="application/json,.json" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (!file) return; void run(async () => { if (file.size > 64000) throw new Error('Route file is too large'); const value = JSON.parse(await file.text()) as FarmingRoute; if (value.version !== 1 || !Array.isArray(value.stops) || value.stops.some(id => typeof id !== 'string')) throw new Error('Unsupported route file'); if (replace({ ...value, id: crypto.randomUUID(), revision: 0 })) setDirty(true); }); }} />
        </details>{route.map_hash !== mapHash && <button onClick={() => change({ ...route, area_id: profile.id, map_hash: mapHash })}>Bind draft to current map</button>}
      </div>
    </fieldset>
    <p>Selecting a path does not start the bot. Review the activity and time limit, then use the dashboard's On control.</p>
    {result && <div role="status">{result.valid ? `${result.legs.length} connections ready within current movement limits.` : <ul>{result.errors.map((error, index) => <li key={index}>{error}</li>)}</ul>}</div>}
    {message && <p role="status">{message}</p>}
  </section>;
}
