import { DRAW, label } from './drawTheme';
import type { AreaProfile, LiveDetections, LivePosition } from './contracts';
import { useRef } from 'react';

/** `compact` is the in-game form: just each place's name, the current one highlighted. */
export function SavedTerrainOverlay({ map, position, alignment, now, compact = false }: {
  map: AreaProfile | null; position?: LivePosition | null; now: number;
  alignment?: LiveDetections['terrain']; compact?: boolean;
}) {
  const retained = useRef<LivePosition | null>(null);
  const independent = alignment !== undefined;
  if (independent) position = alignment;
  const incomingAge = position?.captured_at == null ? Infinity : now - position.captured_at * 1000;
  if (!map || !position || position.area_id !== map.id
    || position.projection && position.projection.revision !== map.revision
    || retained.current?.projection?.revision !== map.revision) retained.current = null;
  if (!independent && position?.kind === 'platform' && !position.stale && position.projection
    && incomingAge >= 0 && incomingAge <= 500) retained.current = position;
  // Brief display-only hold through localization gaps; never renew the captured timestamp.
  const held = !independent && (!position?.projection || position.stale || position.kind !== 'platform' || incomingAge > 500)
    && retained.current?.area_id === map?.id;
  if (held) position = retained.current;
  const projection = position?.projection;
  const age = position?.captured_at == null ? Infinity : now - position.captured_at * 1000;
  if (!map || !position || !projection || position.stale
    || (independent ? !alignment?.alignment.valid : position?.kind !== 'platform')
    || position.area_id !== map.id || projection.revision !== map.revision
    || !Number.isFinite(age) || age < 0 || age > (held ? 750 : 500)
    || ![projection.x, projection.y, projection.scale].every(Number.isFinite)
    || projection.scale < 0.05 || projection.scale > 20) return null;
  const project = (point: { x: number; y: number }) => ({
    x: point.x * projection.scale + projection.x,
    y: point.y * projection.scale + projection.y,
  });
  const extra = position.provisional && position.supplement?.enabled
    ? position.supplement.platform : null;
  const segments = compact ? [...map.platforms, ...map.ropes.filter(rope => rope.name)]
    : [...map.platforms, ...map.ropes];
  return <g aria-label={compact ? 'Platform names' : 'Saved terrain projected onto game'}
    fill="none" strokeWidth="2">
    {segments.map(segment => {
      const start = project(segment.start), end = project(segment.end);
      const matched = !independent && !held && segment.id === position.surface_id;
      const color = matched ? DRAW.current : DRAW.line;
      return <g key={segment.id} stroke={color}>
        <line x1={start.x} y1={start.y} x2={end.x} y2={end.y}
          strokeDasharray={matched ? undefined : '4 5'} strokeWidth={matched ? 3 : 2} vectorEffect="non-scaling-stroke" />
        <text x={start.x} y={start.y - 7} {...label(color)} fontWeight={compact && matched ? 'bold' : 'normal'} fontSize={compact ? 13 : 12}>
          {compact ? segment.name ?? segment.id
            : <>Saved · {segment.name ? `${segment.name} · ${segment.id}` : segment.id}{matched ? ' · spatial match' : ''}</>}</text>
      </g>;
    })}
    {extra && !compact && !independent && !held && extra.id === position.surface_id && <g stroke={DRAW.provisional} aria-label="Provisional middle ledge">
      <line x1={project(extra.start).x} y1={project(extra.start).y}
        x2={project(extra.end).x} y2={project(extra.end).y} strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />
      <text x={project(extra.start).x} y={project(extra.start).y - 7} {...label(DRAW.provisional)} fontSize="12">Provisional · middle ledge · observation only</text>
    </g>}
    {!compact && <text x="12" y="28" {...label(DRAW.note)}
      fontSize="14">Saved terrain · estimated alignment{held ? ' · brief hold' : ''} · not live detection</text>}
  </g>;
}
