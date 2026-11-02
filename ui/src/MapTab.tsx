import { useEffect, useMemo, useRef, useState } from 'react';
import type { EngineClient } from './client';
import type { AreaPoint, AreaProfile, AreaSegment, Snapshot } from './contracts';
import { PathBuilderLibrary } from './PathBuilderLibrary';
import type { FarmingRoute } from './PathBuilder';

type Segment = AreaSegment & { points?: AreaPoint[] };
interface MapEdge { id: string; from: string; to: string; kind: string; proven: boolean }
interface MapNode { id: string; name: string; kind: string; excluded: boolean; unproven?: boolean }
interface RouteMapStatus {
  area_id: string; map_hash?: string; home: string | null; nodes: MapNode[];
  usable_edges: number; proven_edges?: number; edges?: MapEdge[];
}

interface Props {
  snapshot: Snapshot; client: EngineClient; disabled: boolean;
  act: (operation: () => Promise<unknown>) => Promise<void>;
  onPreview: () => void;
  onCircuit?: (route: FarmingRoute | null) => void;
  builderDisabled?: boolean;
}

const line = (item: Segment) => (item.points ?? [item.start, item.end]).map(p => `${p.x},${p.y}`).join(' ');
const middle = (item: Segment) => {
  const points = item.points ?? [item.start, item.end];
  const xs = points.map(p => p.x);
  const x = (Math.min(...xs) + Math.max(...xs)) / 2;
  const right = points.findIndex(p => p.x >= x);
  const a = points[Math.max(0, right - 1)], b = points[Math.max(0, right)];
  const y = b.x === a.x ? a.y : a.y + (b.y - a.y) * (x - a.x) / (b.x - a.x);
  return { x, y };
};

/** Label spots that do not overlap: above the platform, then higher, then below it. */
function placeLabels(platforms: Segment[], size: number) {
  const placed: { x0: number; x1: number; y0: number; y1: number }[] = [];
  return platforms.map(platform => {
    const text = platform.name ? `${platform.name} · ${platform.id}` : platform.id;
    const at = middle(platform), width = text.length * size * 0.56;
    const tries = [at.y - size * 0.45, at.y - size * 1.5, at.y + size * 1.2, at.y - size * 2.55, at.y + size * 2.25];
    const y = tries.find(candidate => !placed.some(b => at.x - width / 2 < b.x1 && at.x + width / 2 > b.x0
      && candidate - size < b.y1 && candidate > b.y0)) ?? tries[0];
    placed.push({ x0: at.x - width / 2, x1: at.x + width / 2, y0: y - size, y1: y });
    return { id: platform.id, x: at.x, y, text };
  });
}

const LABEL_PX = 13; // on-screen label size
// Status marks a reading stale after 0.5 s; at ~2.5 fps that is every other update.
// The map keeps the last position this long (faded) instead of blinking.
const HOLD_MS = 2000;
const LABELS_FROM_PX = 600; // narrower drawings leave names to the list beside them

/** Rendered size of an element, kept current as it resizes. */
function useSize(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: fallback, height: fallback });
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}

/** The whole saved map with every place named; picking a platform previews a route there. */
export function MapTab({ snapshot: s, client, disabled, act, onPreview, onCircuit, builderDisabled = disabled }: Props) {
  const [profile, setProfile] = useState<AreaProfile | null>(null);
  const [error, setError] = useState('');
  const [showMoves, setShowMoves] = useState(false);
  const [large, setLarge] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const [frame, { width: frameWidth }] = useSize(400);
  const [dialog, dialogSize] = useSize(1200);
  const live = s.position?.feet ?? null;
  const last = useRef<{ feet: [number, number]; area?: string; at: number } | null>(null);
  const [, tick] = useState(0);
  if (live) last.current = { feet: live, area: s.position?.area_id, at: Date.now() };
  useEffect(() => {
    if (live) return;
    const timer = setTimeout(() => tick(n => n + 1), HOLD_MS);
    return () => clearTimeout(timer);
  }, [live]);
  const areaId = s.position?.area_id;
  const nav = s.navigation;
  const map = (nav?.map && nav.map.area_id === areaId ? nav.map : null) as RouteMapStatus | null;

  useEffect(() => {
    if (!areaId) { setProfile(null); return; }
    let live = true;
    client.command<{ profile: AreaProfile }>('area_load', { area_id: areaId })
      .then(value => { if (live) { setProfile(value.profile); setError(''); } })
      .catch((reason: unknown) => { if (live) setError(String(reason)); });
    return () => { live = false; };
  }, [areaId, map?.map_hash, client]);

  const nodes = useMemo(() => new Map((map?.nodes ?? []).map(n => [n.id, n])), [map]);
  const builder = <PathBuilderLibrary client={client} disabled={builderDisabled || Boolean(nav?.active) || s.mode !== 'capture'}
    initialArea={areaId} onSelect={onCircuit} />;
  if (!areaId) return <section className="map-tab" aria-label="Map"><h3>See the whole map</h3>
    <p>Track a map from Routes to draw it here with every platform, rope and ladder named.</p>{builder}</section>;
  if (!profile) return <section className="map-tab" aria-label="Map"><h3>See the whole map</h3>
    <p>{error || 'Loading the saved map…'}</p></section>;

  const platforms = profile.platforms as Segment[];
  const ropes = profile.ropes as Segment[];
  const box = profile.boundary;
  const centers = new Map([...platforms, ...ropes].map(item => [item.id, middle(item)]));
  const here = s.position?.kind === 'platform' || s.position?.kind === 'rope' ? s.position.surface_id : null;
  const held = !live && last.current && last.current.area === areaId
    && Date.now() - last.current.at < HOLD_MS ? last.current.feet : null;
  const feet = live ?? held;
  const route = nav?.route && nav.route.area_id === areaId ? nav.route : null;
  const origin = here && nodes.get(here) && !nodes.get(here)!.excluded ? here : map?.home ?? null;
  const name = (id: string) => [...platforms, ...ropes].find(item => item.id === id)?.name ?? id;
  const pick = (target: string) => {
    if (!origin || target === origin || disabled || nav?.active) return;
    void act(async () => {
      const result = await client.command('nav_preview', { origin, target });
      onPreview(); return result;
    });
  };
  const usable = (id: string) => Boolean(map && nodes.get(id) && !nodes.get(id)!.excluded);
  // Screen pixels per map pixel. A tall map is limited by height, not width; the full
  // map may grow to two screens high (scrolling) so its names stay readable.
  const drawing = (width: number, height: number, screens = 1) => {
    const scale = Math.max(Math.min(width / box.width, screens * height / box.height), 1e-3);
    const label = LABEL_PX / scale;
    const size = screens > 1 ? { width: box.width * scale, height: box.height * scale, maxHeight: 'none' } : undefined;
    return <svg className="map-drawing" role="img" aria-label={`Map of ${profile.name}`} style={size}
    viewBox={`${box.x} ${box.y} ${box.width} ${box.height}`} preserveAspectRatio="xMidYMid meet">
    {profile.zones.map(zone => <rect key={zone.id} className={`map-zone map-zone-${zone.kind}`}
      x={zone.rect.x} y={zone.rect.y} width={zone.rect.width} height={zone.rect.height}><title>Portal · keep clear</title></rect>)}
    {showMoves && (map?.edges ?? []).map(edge => {
      const a = centers.get(edge.from), b = centers.get(edge.to);
      return a && b ? <line key={edge.id} className={edge.proven ? 'map-move proven' : 'map-move'}
        x1={a.x} y1={a.y} x2={b.x} y2={b.y} /> : null;
    })}
    {route?.edges.map(edge => <polyline key={edge.id} className="map-route"
      points={[edge.launch, edge.landing].map(p => p.join(',')).join(' ')} />)}
    {ropes.map(rope => <g key={rope.id}>
      <polyline className={`map-rope ${rope.name?.startsWith('Ladder') ? 'ladder' : ''} ${focus === rope.id ? 'focus' : ''}`} points={line(rope)} />
      <title>{rope.name}</title></g>)}
    {platforms.map(platform => <g key={platform.id} className={`map-platform ${here === platform.id ? 'here' : ''} ${focus === platform.id ? 'focus' : ''} ${map && !usable(platform.id) ? 'unavailable' : ''}`}
      onClick={() => pick(platform.id)}>
      <polyline className="map-hit" points={line(platform)} />
      <polyline points={line(platform)} />
      <title>{platform.name}{map && !usable(platform.id) ? ' · no safe route' : ''}</title></g>)}
    {width >= LABELS_FROM_PX && placeLabels(platforms, label).map(spot => <text key={spot.id} className="map-label"
      x={spot.x} y={spot.y} fontSize={label} textAnchor="middle">{spot.text}</text>)}
    {feet && <circle className={live ? 'map-player' : 'map-player stale'} cx={feet[0]} cy={feet[1] - label * 0.5} r={label * 0.5}><title>You</title></circle>}
  </svg>;
  };

  const proven = map?.proven_edges ?? 0;
  return <section className="map-tab" aria-label="Map">
    <span className="eyebrow">{profile.name}</span>
    <h3>{here ? `You are on ${name(here)}` : 'Where you are is unknown'}</h3>
    <p>Pick a platform on the map or in the list to preview a route to it. Nothing moves until you start a supervised route.
      {frameWidth < LABELS_FROM_PX && ' Point at a name in the list to find it on the map, or open the full map to see every name.'}</p>
    <div className="map-frame" ref={frame}>{drawing(frameWidth, 0.7 * window.innerHeight)}</div>
    <div className="map-actions">
      <button onClick={() => setLarge(true)}>Open full map</button>
      {map && <label className="map-toggle"><input type="checkbox" checked={showMoves} onChange={e => setShowMoves(e.target.checked)} /> Show moves</label>}
    </div>
    {map && <p className="map-proof">{proven} of {map.usable_edges} moves proven. Unproven moves run only on supervised routes; rotation waits until they succeed once.</p>}
    <ol className="map-places" aria-label="Places on this map">
      {[...platforms].sort((a, b) => middle(b).y - middle(a).y).map(platform => <li key={platform.id}>
        <button disabled={disabled || !usable(platform.id) || platform.id === origin || Boolean(nav?.active)}
          onMouseEnter={() => setFocus(platform.id)} onMouseLeave={() => setFocus(null)}
          onFocus={() => setFocus(platform.id)} onBlur={() => setFocus(null)}
          onClick={() => pick(platform.id)}>{platform.name}{platform.id === here ? ' · you' : ''}</button>
      </li>)}
      {ropes.map(rope => <li key={rope.id} className="map-place-rope"
        onMouseEnter={() => setFocus(rope.id)} onMouseLeave={() => setFocus(null)}>{rope.name}</li>)}
    </ol>
    {builder}
    {large && <div className="map-dialog" role="dialog" aria-modal="true" aria-label={`Full map of ${profile.name}`}
      onKeyDown={e => { if (e.key === 'Escape') setLarge(false); }}>
      <div className="map-dialog-bar"><strong>{profile.name}</strong>
        <button autoFocus onClick={() => setLarge(false)}>Close</button></div>
      <div className="map-dialog-body" ref={dialog}>{drawing(dialogSize.width, dialogSize.height, 2)}</div>
    </div>}
  </section>;
}
