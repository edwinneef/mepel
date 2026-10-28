import type { Detection, Snapshot } from './contracts';

export function AttackRangeOverlay({ player, setup, threshold = 0.9 }: {
  player: Detection | null; setup: Snapshot['attack_setup']; threshold?: number;
}) {
  if (!player || player.tracked || player.confidence < threshold || !setup) return null;
  const { minimum_px: min, maximum_px: max } = setup;
  if (![min, max].every(Number.isFinite) || min < 0 || max <= 0 || min > max) return null;
  const { x, y, width, height } = player.box;
  const center = x + width / 2;
  const baseline = y + height + 14;
  const color = '#91c8ff';
  return <g aria-label="Configured attack range" fill="none" stroke={color} strokeWidth="2" pointerEvents="none">
    <title>Horizontal distance from player centre, shared by basic attack and skill. Same-platform targeting still applies.</title>
    {[-1, 1].map(side => <g key={side}>
      <rect x={side < 0 ? center - max : center + min} y={y} width={max - min} height={height}
        fill={color} fillOpacity="0.07" stroke="none" />
      <line x1={center + side * min} x2={center + side * max} y1={baseline} y2={baseline}
        vectorEffect="non-scaling-stroke" />
      <line x1={center + side * max} x2={center + side * max} y1={y - 4} y2={baseline + 5}
        strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
      {min > 0 && <line x1={center + side * min} x2={center + side * min} y1={y - 4} y2={baseline + 5}
        stroke="#ffb967" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />}
    </g>)}
    {min > 0 && <rect x={center - min} y={y} width={min * 2} height={height}
      fill="#ffb967" fillOpacity="0.1" stroke="none" />}
    <line x1={center} x2={center} y1={baseline - 4} y2={baseline + 4} vectorEffect="non-scaling-stroke" />
    <text x={center} y={Math.max(14, y - 24)} textAnchor="middle" fill={color}
      stroke="#091019" strokeWidth="3" paintOrder="stroke" fontSize="12">
      Attack {min}–{max} px · {setup.measured ? 'measured' : 'unmeasured'}
    </text>
    <text x={center} y={baseline + 18} textAnchor="middle" fill={color}
      stroke="#091019" strokeWidth="3" paintOrder="stroke" fontSize="11">
      {min > 0 ? 'Orange: too close · ' : ''}Horizontal reach · both attacks
    </text>
  </g>;
}
