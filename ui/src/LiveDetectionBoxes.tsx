import { useEffect, useRef, useState } from 'react';
import type { Detection, LiveDetections } from './contracts';

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
      strokeWidth="3" paintOrder="stroke" fontSize="13">{key} · {item.tracked ? 'tracked' : `${Math.round(item.confidence * 100)}% similarity`}</text>
  </g>;
  return <g aria-label="Detection boxes">
    {player && box(player, 'Player', '#81edbb')}
    {monsters.map((item, i) => box(item, `${item.kind} ${i + 1}`, '#ffbd72'))}
    {drawing.target && box(monsters.find((item, i) => drawing.target?.track_id
      ? item.track_id === drawing.target.track_id
      : observed[i].template === drawing.target?.template && distance(observed[i], drawing.target!) < 1)
      ?? drawing.target, 'Target', '#ff6b89')}
  </g>;
}
