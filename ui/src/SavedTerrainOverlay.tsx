import type { AreaProfile, LivePosition } from './contracts';

export function SavedTerrainOverlay({ map, position, now }: {
  map: AreaProfile | null; position?: LivePosition | null; now: number;
}) {
  const projection = position?.projection;
  const age = position?.captured_at == null ? Infinity : now - position.captured_at * 1000;
  if (!map || !projection || position?.stale || position?.kind !== 'platform'
    || position.area_id !== map.id || projection.revision !== map.revision
    || !Number.isFinite(age) || age < 0 || age > 500
    || ![projection.x, projection.y, projection.scale].every(Number.isFinite)
    || projection.scale < 0.05 || projection.scale > 20) return null;
  const project = (point: { x: number; y: number }) => ({
    x: point.x * projection.scale + projection.x,
    y: point.y * projection.scale + projection.y,
  });
  const extra = position.provisional && position.supplement?.enabled
    ? position.supplement.platform : null;
  return <g aria-label="Saved terrain projected onto game" fill="none" strokeWidth="2">
    {[...map.platforms, ...map.ropes].map(segment => {
      const start = project(segment.start), end = project(segment.end);
      const matched = segment.id === position.surface_id;
      const color = matched ? '#91c8ff' : '#c8a5ff';
      return <g key={segment.id} stroke={color}>
        <line x1={start.x} y1={start.y} x2={end.x} y2={end.y}
          strokeDasharray={matched ? '8 3' : '4 5'} vectorEffect="non-scaling-stroke" />
        <text x={start.x} y={start.y - 7} fill={color} stroke="#091019" strokeWidth="3"
          paintOrder="stroke" fontSize="12">Saved · {segment.name || segment.id}{matched ? ' · spatial match' : ''}</text>
      </g>;
    })}
    {extra && extra.id === position.surface_id && <g stroke="#ffd07a" aria-label="Provisional middle ledge">
      <line x1={project(extra.start).x} y1={project(extra.start).y}
        x2={project(extra.end).x} y2={project(extra.end).y} strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />
      <text x={project(extra.start).x} y={project(extra.start).y - 7} fill="#ffd07a"
        stroke="#091019" strokeWidth="3" paintOrder="stroke" fontSize="12">Provisional · middle ledge · observation only</text>
    </g>}
    <text x="12" y="28" fill="#c8a5ff" stroke="#091019" strokeWidth="3" paintOrder="stroke"
      fontSize="14">Saved terrain · estimated alignment · not live detection</text>
  </g>;
}
