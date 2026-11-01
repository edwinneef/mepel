import { useEffect, useRef, useState } from 'react';
import type { Detection, EnemyTrack, LiveDetections, PlayerTracking } from './contracts';

const identity = (d: Detection) => d.template.startsWith('catalog:')
  ? d.template.slice(0, d.template.lastIndexOf(':')) : d.template;
const distance = (a: Detection, b: Detection) => Math.hypot(
  a.box.x + a.box.width / 2 - b.box.x - b.box.width / 2,
  a.box.y + a.box.height / 2 - b.box.y - b.box.height / 2,
);

// Display prediction only. Never modifies snapshots used for decisions or input gates.
export function predictBoxes(current: Detection[], previous: Detection[], dt: number, age: number) {
  if (dt < .05 || dt > .6 || age < 0 || age > 750) return current;
  return current.map(item => {
    if (item.tracked) return item;
    const matches = previous.filter(old => !old.tracked && identity(old) === identity(item))
      .sort((a, b) => distance(a, item) - distance(b, item));
    const old = matches[0];
    if (!old || distance(old, item) > 100
      || matches[1] && distance(matches[1], item) - distance(old, item) < 20) return item;
    // Reject crossings where another current detection is equally close to this old box.
    if (current.some(other => other !== item && identity(other) === identity(item)
      && distance(other, old) <= distance(item, old) + 10)) return item;
    const horizon = Math.min(age, 250) / 1000;
    const dx = (item.box.x - old.box.x) / dt * horizon;
    const dy = (item.box.y - old.box.y) / dt * horizon;
    if (Math.hypot(dx, dy) > 80) return item;
    return { ...item, box: { ...item.box, x: item.box.x + dx, y: item.box.y + dy } };
  });
}

// Fast image tracking already accounts for most of the motion. Only bridge the
// small capture/transport gap, using stable IDs rather than reassociating species.
export function projectDisplayBoxes(current: Detection[], previous: Detection[], dt: number, age: number) {
  if (dt <= 0 || dt > .2 || age < 0 || age > 500) return current;
  return current.map(item => {
    if (!item.track_id) return item;
    const old = previous.find(candidate => candidate.track_id === item.track_id);
    if (!old || identity(old) !== identity(item)) return item;
    const horizon = Math.min(age, 50) / 1000;
    const dx = (item.box.x - old.box.x) / dt * horizon;
    const dy = (item.box.y - old.box.y) / dt * horizon;
    // Reacquisition/recognition corrections are not velocity measurements.
    if (distance(item, old) > 32 || Math.hypot(dx, dy) > 20) return item;
    return { ...item, box: { ...item.box, x: item.box.x + dx, y: item.box.y + dy } };
  });
}

export function LiveDetectionBoxes({ drawing }: { drawing: LiveDetections }) {
  const [now, setNow] = useState(Date.now());
  const history = useRef<{ current: LiveDetections; previous?: LiveDetections }>({ current: drawing });
  if (history.current.current.frame.id !== drawing.frame.id
    || history.current.current.frame.source_id !== drawing.frame.source_id) {
    const old = history.current.current;
    history.current = { current: drawing,
      previous: old.frame.source_id === drawing.frame.source_id
        && old.frame.width === drawing.frame.width && old.frame.height === drawing.frame.height ? old : undefined };
  }
  useEffect(() => {
    let frame: number;
    const paint = () => { setNow(Date.now()); frame = requestAnimationFrame(paint); };
    frame = requestAnimationFrame(paint);
    return () => cancelAnimationFrame(frame);
  }, []);
  const previous = history.current.previous;
  const captured = drawing.frame.captured_at;
  if (captured == null) return null;
  const age = Math.max(now, Date.now()) - captured * 1000;
  if (drawing.display && (age < 0 || age >= 500)) return null;
  const dt = previous?.frame.captured_at == null ? 0 : captured - previous.frame.captured_at;
  const observed = drawing.monsters ?? [];
  const project = drawing.display ? projectDisplayBoxes : predictBoxes;
  const monsters = project(observed, previous?.monsters ?? [], dt, age);
  const player = drawing.display && drawing.player
    ? projectDisplayBoxes([drawing.player], previous?.player ? [previous.player] : [], dt, age)[0] : drawing.player;
  const box = (item: Detection, key: string, color: string) => <g key={`${key === 'Target' ? 'target:' : ''}${item.track_id ?? key}`} stroke={color}>
    <rect {...item.box} fill="none" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    <text x={item.box.x} y={Math.max(14, item.box.y - 5)} fill={color} stroke="#091019"
      strokeWidth="3" paintOrder="stroke" fontSize="13">{key} Â· {item.tracked ? 'tracked' : `${Math.round(item.confidence * 100)}% similarity`}</text>
  </g>;
  return <g aria-label="Detection boxes">
    {player && box(player, 'Player', '#81edbb')}
    {monsters.map((item, i) => box(item, `${item.kind} ${i + 1}`, '#ffbd72'))}
    {drawing.target && box(monsters.find((item, i) => drawing.target?.track_id
      ? item.track_id === drawing.target.track_id
      : observed[i].template === drawing.target?.template && distance(observed[i], drawing.target!) < 1)
      ?? drawing.target, 'Target', '#ff6b89')}
    {age >= 0 && age <= 500 && <EnemyTrackDiagnostics tracks={drawing.enemy_tracks ?? []} />}
    {age >= 0 && age <= 500 && drawing.player_tracking
      && <PlayerTrackDiagnostics tracking={drawing.player_tracking} />}
  </g>;
}

export function EnemyTrackDiagnostics({ tracks }: { tracks: EnemyTrack[] }) {
  return <g aria-label="Enemy tracking diagnostics">{tracks.map(track => {
    const [x, y] = track.predicted_position;
    const [ux, uy] = track.uncertainty;
    const color = track.state === 'visible' ? '#ffbd72' : '#aab9ca';
    return <g key={track.track_id} stroke={color}>
      <ellipse cx={x} cy={y} rx={ux} ry={uy} fill="none" strokeDasharray="4 3" />
      <path d={`M${x - 4} ${y}h8 M${x} ${y - 4}v8`} />
      {track.visible_bounds && <rect {...track.visible_bounds} fill="none" strokeDasharray="2 2" />}
      <text x={x + 6} y={y + 17} fill={color} stroke="#091019" strokeWidth="3"
        paintOrder="stroke" fontSize="11">{track.track_id} Â· {track.state} Â· {Math.round(track.confidence * 100)}%
        {` Â· (${Math.round(x)}, ${Math.round(y)}) Â±${Math.round(ux)},${Math.round(uy)}`}
        {track.observed ? ' Â· pixels observed' : ' Â· prediction only'}</text>
    </g>;
  })}</g>;
}

// Player track debug: search window, predicted box and state. Display only.
export function PlayerTrackDiagnostics({ tracking }: { tracking: PlayerTracking }) {
  const { search, predicted, observed, state } = tracking;
  const color = state === 'confirmed' ? '#81edbb' : state === 'lost' ? '#ff6b89' : '#aab9ca';
  const anchor = observed ?? predicted;
  return <g aria-label="Player tracking diagnostics" fill="none">
    {search && <rect {...search} stroke="#6f8bb3" strokeDasharray="6 4" strokeWidth="1"
      vectorEffect="non-scaling-stroke" />}
    {predicted && <rect {...predicted} stroke={color} strokeDasharray="3 3" strokeWidth="1"
      vectorEffect="non-scaling-stroke" />}
    {anchor && <text x={anchor.x} y={anchor.y + anchor.height + 16} fill={color} stroke="#091019"
      strokeWidth="3" paintOrder="stroke" fontSize="11">track · {state} · {Math.round(tracking.confidence * 100)}%
      {tracking.since_confirmed != null && ` · ${tracking.since_confirmed.toFixed(1)}s since confirmed`}
      {tracking.identity ? '' : ' · identity unconfirmed'}</text>}
  </g>;
}
