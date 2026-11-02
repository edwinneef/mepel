import type { ReactNode } from 'react';
import type { AreaProfile, Snapshot } from './contracts';
import { useHeldPosition } from './heldPosition';

// Presentational pieces of the dashboard page. They read the snapshot and never send commands.

export function Gauge({ label, kind, percent, threshold }: {
  label: string; kind: 'hp' | 'mp'; percent: number | null | undefined; threshold: number;
}) {
  const known = typeof percent === 'number';
  const value = known ? Math.max(0, Math.min(100, percent)) : 0;
  return <div className={`dash-gauge ${known && value < threshold + 10 ? 'low' : ''}`}
    title={`${label} potion trigger at ${threshold}%`}>
    <span className="dash-gauge-label">{label}</span>
    <div className={`dash-bar ${kind}`} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={known ? Math.round(value) : undefined} aria-valuetext={known ? `${Math.round(value)}%` : 'Not read yet'}>
      <i style={{ width: `${value}%` }} />
      <b style={{ left: `${threshold}%` }} aria-hidden="true" />
    </div>
    <span className="dash-gauge-value">{known ? `${Math.round(value)}%` : '—'}</span>
  </div>;
}

export function Facts({ snapshot: s }: { snapshot: Snapshot | null }) {
  const spot = useHeldPosition(s?.position);
  const feet = spot.feet;
  const tracks = s?.enemy_tracks?.filter(track => track.state !== 'lost').length;
  const player = s?.player_tracking?.state ?? (s?.player ? (s.player.tracked ? 'tracked' : 'confirmed') : 'not recognized');
  const confidence = s?.player_tracking?.confidence ?? s?.player?.confidence;
  const rows: [string, ReactNode][] = [
    ['Map', s?.position?.area_name || s?.catalog?.active_map || s?.window?.title || '—'],
    ['Foothold', spot.surface || '—'],
    ['Position', feet ? `${Math.round(feet[0])}, ${Math.round(feet[1])}` : '—'],
    ['Player', `${player[0].toUpperCase()}${player.slice(1)}${confidence != null && s?.player ? ` (${confidence.toFixed(2)})` : ''}`],
    ['Enemies', `${tracks ?? s?.monsters?.length ?? 0} tracked`],
    ['Capture', s?.fps != null ? `${s.fps.toFixed(1)} fps${s.latency_ms != null ? ` · ${Math.round(s.latency_ms)} ms` : ''}` : '—'],
  ];
  return <dl className="dash-facts">{rows.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl>;
}

export function SpotMap({ map, snapshot: s }: { map: AreaProfile | null; snapshot: Snapshot | null }) {
  const spot = useHeldPosition(s?.position);
  if (!map) return <p className="dash-empty">No saved map for this spot yet. Track or import one under Map tracking.</p>;
  const b = map.boundary;
  const here = spot.area === map.id;
  const feet = here ? spot.feet : null;
  const stroke = Math.max(b.width, b.height) / 120;
  return <svg className="dash-spot" viewBox={`${b.x} ${b.y} ${b.width} ${b.height}`} role="img"
    aria-label={`Saved map ${map.name}: ${map.platforms.length} platforms, ${map.ropes.length} ropes`}>
    {map.ropes.map(rope => <line key={rope.id} x1={rope.start.x} y1={rope.start.y} x2={rope.end.x} y2={rope.end.y}
      className="rope" strokeWidth={stroke * .7} />)}
    {map.platforms.map(platform => <line key={platform.id} x1={platform.start.x} y1={platform.start.y} x2={platform.end.x} y2={platform.end.y}
      className={here && platform.id === spot.surface ? 'platform current' : 'platform'} strokeWidth={stroke} strokeLinecap="round" />)}
    {feet && <circle cx={feet[0]} cy={feet[1] - stroke * 2} r={stroke * 2} className="player" />}
  </svg>;
}

export function Journal({ history }: { history: Snapshot['history'] | undefined }) {
  const entries = [...(history ?? [])].sort((a, b) => b.time - a.time).slice(0, 40);
  if (!entries.length) return <p className="dash-empty">Nothing has happened in this session yet.</p>;
  return <ol className="dash-journal">{entries.map((entry, index) => <li key={`${entry.time}-${index}`}>
    <time>{new Date(entry.time * 1000).toLocaleTimeString([], { hour12: false })}</time><span>{entry.reason}</span>
  </li>)}</ol>;
}

const icons: Record<string, ReactNode> = {
  Overview: <path fill="#f2843b" d="M12 2l2 4 4-1-1 4 4 2-4 2 1 4-4-1-2 4-2-4-4 1 1-4-4-2 4-2-1-4 4 1z" />,
  Bot: <><path d="M5 3q12 9 0 18" stroke="#c9884a" strokeWidth="2.2" fill="none" /><path d="M5 3v18" stroke="#fbeedb" strokeWidth="1" /><path d="M4 12h16l-3-3m3 3l-3 3" stroke="#ffc94a" strokeWidth="2" fill="none" /></>,
  Connection: <><rect x="3" y="4" width="18" height="12" rx="2" fill="#5fb6e8" /><path d="M8 20h8M12 16v4" stroke="#cbb091" strokeWidth="2" /></>,
  Recognition: <><circle cx="10" cy="10" r="6" fill="none" stroke="#ffc94a" strokeWidth="2.4" /><path d="M14.5 14.5L20 20" stroke="#ffc94a" strokeWidth="2.6" strokeLinecap="round" /></>,
  Potions: <><rect x="9" y="1.5" width="6" height="4" rx="1" fill="#b07a46" /><path d="M7 8q5-4 10 0l2 9a4 4 0 01-4 5H9a4 4 0 01-4-5z" fill="#e8443a" /></>,
  Map: <><rect x="2" y="4" width="20" height="16" rx="2" fill="#d9c08a" /><path d="M5 15h6M13 10h6M8 15v-5" stroke="#7a4b1e" strokeWidth="2" /></>,
  Diagnostics: <path d="M2 13h4l2-6 4 12 3-8 2 2h5" stroke="#8bd04e" strokeWidth="2.2" fill="none" strokeLinejoin="round" />,
};

export function NavIcon({ name }: { name: string }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true">{icons[name]}</svg>;
}
