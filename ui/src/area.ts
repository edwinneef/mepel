import type { AreaPoint, AreaProfile, AreaSegment, AreaView, Rect } from './contracts';
import { rectangle } from './selection';

export type DrawTool = 'select' | 'boundary' | 'avoid' | 'portal' | 'platform' | 'rope';
export const newElementId = (prefix: string) => `${prefix}_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
const rounded = (value: number) => Math.round(value * 1000) / 1000;
export const toArea = (point: AreaPoint, view: AreaView): AreaPoint => ({
  x: rounded(point.x / view.scale + view.origin.x), y: rounded(point.y / view.scale + view.origin.y),
});
export const toView = (point: AreaPoint, view: AreaView): AreaPoint => ({
  x: (point.x - view.origin.x) * view.scale, y: (point.y - view.origin.y) * view.scale,
});

export function newArea(): AreaProfile {
  return {
    schema_version: 1, id: crypto.randomUUID().replaceAll('-', ''), revision: 0,
    name: 'New hunting area', boundary: { x: 0, y: 0, width: 1, height: 1 },
    views: [], zones: [], platforms: [], ropes: [], links: [],
  };
}

export function drawArea(
  profile: AreaProfile, view: AreaView, tool: Exclude<DrawTool, 'select'>,
  from: AreaPoint, to: AreaPoint,
): { profile: AreaProfile; selected: string } {
  const start = toArea(from, view);
  const end = toArea(to, view);
  if (tool === 'platform' || tool === 'rope') {
    if (tool === 'rope') end.x = start.x;
    if (start.x === end.x && start.y === end.y) throw new Error('Draw a segment with two different endpoints.');
    const segment = { id: newElementId(tool), start, end };
    const key = tool === 'platform' ? 'platforms' : 'ropes';
    return { profile: { ...profile, [key]: [...profile[key], segment] }, selected: segment.id };
  }
  const rect = rectangle(start, end);
  if (rect.width < 1 || rect.height < 1) throw new Error('Draw a rectangle at least one area pixel wide and high.');
  if (tool === 'boundary') return { profile: { ...profile, boundary: rect }, selected: 'boundary' };
  const zone = { id: newElementId(tool), kind: tool, rect };
  return { profile: { ...profile, zones: [...profile.zones, zone] }, selected: zone.id };
}

export function removeAreaItem(profile: AreaProfile, id: string): AreaProfile {
  return {
    ...profile,
    zones: profile.zones.filter(item => item.id !== id),
    platforms: profile.platforms.filter(item => item.id !== id),
    ropes: profile.ropes.filter(item => item.id !== id),
    links: profile.links.filter(item => item.id !== id && item.from !== id && item.to !== id),
  };
}

function inside(point: AreaPoint, boundary: Rect): boolean {
  return point.x >= boundary.x && point.y >= boundary.y
    && point.x <= boundary.x + boundary.width && point.y <= boundary.y + boundary.height;
}

export function areaErrors(profile: AreaProfile): string[] {
  const errors: string[] = [];
  if (!profile.name.trim()) errors.push('Give this hunting area a name.');
  if (!profile.views.length) errors.push('Capture at least one reference view.');
  if (![profile.boundary.x, profile.boundary.y, profile.boundary.width, profile.boundary.height].every(Number.isFinite)
    || profile.boundary.width <= 0 || profile.boundary.height <= 0) errors.push('Use a finite, positive hunting boundary.');
  for (const item of [...profile.platforms, ...profile.ropes]) {
    if (!inside(item.start, profile.boundary) || !inside(item.end, profile.boundary)) errors.push(`${item.id} lies outside the hunting boundary.`);
  }
  for (const item of profile.zones) {
    if (!inside(item.rect, profile.boundary)
      || !inside({ x: item.rect.x + item.rect.width, y: item.rect.y + item.rect.height }, profile.boundary)) errors.push(`${item.id} lies outside the hunting boundary.`);
  }
  return errors;
}

export function graphWarnings(profile: AreaProfile): string[] {
  if (!profile.platforms.length) return ['No platform has been taught yet.'];
  const visited = new Set([profile.platforms[0].id]);
  const pending = [...visited];
  while (pending.length) {
    const from = pending.shift();
    for (const link of profile.links) if (link.from === from && !visited.has(link.to)) {
      visited.add(link.to); pending.push(link.to);
    }
  }
  const missing = [...profile.platforms, ...profile.ropes].filter(item => !visited.has(item.id));
  return missing.length ? [`Not reachable from ${profile.platforms[0].id}: ${missing.map(item => item.id).join(', ')}`] : [];
}

export const midpoint = (segment: AreaSegment): AreaPoint => ({
  x: (segment.start.x + segment.end.x) / 2, y: (segment.start.y + segment.end.y) / 2,
});

export function hitArea(profile: AreaProfile, point: AreaPoint, tolerance: number): string | null {
  for (const segment of [...profile.ropes, ...profile.platforms]) {
    const dx = segment.end.x - segment.start.x, dy = segment.end.y - segment.start.y;
    const t = Math.max(0, Math.min(1, ((point.x - segment.start.x) * dx + (point.y - segment.start.y) * dy) / (dx * dx + dy * dy)));
    if (Math.hypot(point.x - segment.start.x - t * dx, point.y - segment.start.y - t * dy) <= tolerance) return segment.id;
  }
  return [...profile.zones].reverse().find(zone => inside(point, zone.rect))?.id ?? null;
}
