import type { AreaPoint, AreaProfile } from './contracts';

/** A trusted move from `farm_route_map`: the same subset validation plans over. */
export interface RouteMove { id: string; kind: string; from: string; to: string; launch: number[]; landing: number[] }
export interface RouteOptions { farmable?: string[]; moves?: RouteMove[] }
export interface PlannedLeg { origin: string; target: string; moves: RouteMove[] | null; start: number[]; end: number[] }
export interface Suggestion { id: string; name: string; why: string; stops: string[] }

type Platform = AreaProfile['platforms'][number] & { points?: AreaPoint[] };
const pointsOf = (p: Platform) => p.points?.length ? p.points : [p.start, p.end];
export const center = (p: Platform) => ({ x: (p.start.x + p.end.x) / 2, y: (p.start.y + p.end.y) / 2 });
const dist = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** Preview only. Mirrors the engine planner's cost (travel + 100 per move, eight-move budget)
 * so the drawing usually matches; `farm_route_validate` stays the authority on save. */
export function planLeg(moves: RouteMove[], origin: string, target: string, feet: number[]): RouteMove[] | null {
  if (origin === target) return [];
  const best = new Map<string, number>();
  const queue: { cost: number; node: string; path: RouteMove[]; feet: number[] }[] = [{ cost: 0, node: origin, path: [], feet }];
  while (queue.length) {
    queue.sort((a, b) => a.cost - b.cost);
    const current = queue.shift()!;
    if (current.node === target) return current.path;
    if (current.path.length >= 8) continue;
    for (const move of moves) {
      if (move.from !== current.node) continue;
      const cost = current.cost + dist(current.feet, move.launch) + dist(move.launch, move.landing) + 100;
      const key = `${move.id}:${current.path.length + 1}`;
      if (cost >= (best.get(key) ?? Infinity)) continue;
      best.set(key, cost);
      queue.push({ cost, node: move.to, path: [...current.path, move], feet: move.landing });
    }
  }
  return null;
}

export function usableMoves(options: RouteOptions, disabled: string[] = []) {
  return (options.moves ?? []).filter(move => !disabled.includes(move.id));
}

export function planRoute(profile: AreaProfile, moves: RouteMove[], stops: string[], loop: boolean): PlannedLeg[] {
  const byId = new Map(profile.platforms.map(p => [p.id, p as Platform]));
  const pairs = stops.slice(1).map((target, index) => [stops[index], target]);
  if (loop && stops.length > 1) pairs.push([stops.at(-1)!, stops[0]]);
  const first = byId.get(stops[0]);
  let feet = first ? [center(first).x, center(first).y] : [0, 0];
  return pairs.map(([origin, target]) => {
    const planned = planLeg(moves, origin, target, feet);
    const start = feet;
    const goal = byId.get(target);
    feet = planned?.length ? planned.at(-1)!.landing : goal ? [center(goal).x, center(goal).y] : feet;
    return { origin, target, moves: planned, start, end: feet };
  });
}

/** Nearest-neighbour order from the first stop, by number of moves, then travel distance. */
export function shortestOrder(profile: AreaProfile, moves: RouteMove[], stops: string[]): string[] {
  if (stops.length < 3) return [...stops];
  const byId = new Map(profile.platforms.map(p => [p.id, p as Platform]));
  const feetOf = (id: string) => { const p = byId.get(id); return p ? [center(p).x, center(p).y] : [0, 0]; };
  const left = stops.slice(1), order = [stops[0]];
  while (left.length) {
    const from = order.at(-1)!;
    const score = (id: string) => { const path = planLeg(moves, from, id, feetOf(from)); return path ? path.length * 1e6 + dist(feetOf(from), feetOf(id)) : Infinity; };
    left.sort((a, b) => score(a) - score(b));
    order.push(left.shift()!);
  }
  return order;
}

/** An order whose loop plans, or null. Nearest-first ends with one long trip home, which on tall
 * maps exceeds the planner's eight-move budget; then try a zig-zag: up through every other
 * level and down through the rest, so every trip stays short. */
export function loopOrder(profile: AreaProfile, moves: RouteMove[], stops: string[]): string[] | null {
  const byId = new Map(profile.platforms.map(p => [p.id, p as Platform]));
  const y = (id: string) => { const p = byId.get(id); return p ? center(p).y : 0; };
  const byHeight = [...stops].sort((a, b) => y(b) - y(a));
  const zigzag = [...byHeight.filter((_, i) => i % 2 === 0), ...byHeight.filter((_, i) => i % 2 === 1).reverse()];
  return [shortestOrder(profile, moves, stops), zigzag].find(order => planRoute(profile, moves, order, true).every(leg => leg.moves)) ?? null;
}

/** Ready-made starting points from the farmable platforms; each must plan as a loop. */
export function suggestions(profile: AreaProfile, options: RouteOptions): Suggestion[] {
  const moves = usableMoves(options);
  const farmable = profile.platforms.filter(p => options.farmable?.includes(p.id)) as Platform[];
  if (farmable.length < 2 || !moves.length) return [];
  const ys = farmable.map(p => center(p).y).sort((a, b) => a - b);
  const midY = (ys[Math.floor((ys.length - 1) / 2)] + ys[Math.ceil((ys.length - 1) / 2)]) / 2;
  const midX = profile.boundary.x + profile.boundary.width / 2;
  // Start low and left: the usual place a player arrives on a grinding map.
  const start = (list: Platform[]) => [...list].sort((a, b) => center(b).y - center(a).y || center(a).x - center(b).x).map(p => p.id);
  const candidates = [
    { id: 'all', name: 'Whole map', why: 'Every platform the bot can reach, shortest trip first.', list: farmable },
    { id: 'lower', name: 'Lower floors', why: 'The lower half of the map. Short trips, few climbs.', list: farmable.filter(p => center(p).y >= midY) },
    { id: 'upper', name: 'Upper floors', why: 'The upper half of the map.', list: farmable.filter(p => center(p).y < midY) },
    { id: 'left', name: 'Left side', why: 'Platforms on the left half.', list: farmable.filter(p => center(p).x < midX) },
    { id: 'right', name: 'Right side', why: 'Platforms on the right half.', list: farmable.filter(p => center(p).x >= midX) },
  ];
  const seen = new Set<string>();
  return candidates.flatMap(({ list, ...rest }) => {
    if (list.length < 2) return [];
    const key = list.map(p => p.id).sort().join(',');
    if (seen.has(key)) return [];
    const stops = loopOrder(profile, moves, start(list));
    if (!stops) return [];
    seen.add(key);
    return [{ ...rest, stops }];
  });
}

/** Platform under a map point, within `reach` map units of its line. */
export function platformAt(profile: AreaProfile, point: { x: number; y: number }, reach: number): string | null {
  let found: string | null = null, nearest = reach;
  for (const platform of profile.platforms as Platform[]) {
    const points = pointsOf(platform);
    for (let index = 1; index < points.length; index++) {
      const a = points[index - 1], b = points[index];
      const length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      const t = Math.max(0, Math.min(1, ((point.x - a.x) * (b.x - a.x) + (point.y - a.y) * (b.y - a.y)) / length ** 2));
      const d = Math.hypot(point.x - (a.x + t * (b.x - a.x)), point.y - (a.y + t * (b.y - a.y)));
      if (d <= nearest) { nearest = d; found = platform.id; }
    }
  }
  return found;
}

/** SVG paths for one leg as it happens in game: walk to each launch point, then the move. */
export function legPaths(leg: PlannedLeg, lift = 10) {
  const walks: string[] = [], hops: string[] = [];
  let feet = leg.start;
  for (const move of leg.moves ?? []) {
    const [lx, ly] = move.launch, [tx, ty] = move.landing;
    if (dist(feet, move.launch) > 4) walks.push(`M${feet[0]},${feet[1] - lift} L${lx},${ly - lift}`);
    if (move.kind === 'jump') hops.push(`M${lx},${ly - lift} Q${(lx + tx) / 2},${Math.min(ly, ty) - lift - 60} ${tx},${ty - lift}`);
    else if (move.kind === 'drop') hops.push(`M${lx},${ly - lift} Q${tx},${ly - lift - 25} ${tx},${ty - lift}`);
    else hops.push(`M${lx},${ly - lift} L${tx},${ty - lift}`);
    feet = move.landing;
  }
  return { walks, hops };
}

export const moveWords: Record<string, string> = { walk: 'walk', climb: 'climb', drop: 'drop down', jump: 'jump' };
export function legText(leg: PlannedLeg, names: Map<string, string>) {
  if (!leg.moves) return `No trusted move reaches ${names.get(leg.target) ?? leg.target} from here.`;
  let feet = leg.start;
  const text = leg.moves.map(move => {
    const side = move.launch[0] < feet[0] - 4 ? 'go left, ' : move.launch[0] > feet[0] + 4 ? 'go right, ' : '';
    feet = move.landing;
    return `${side}${moveWords[move.kind] ?? move.kind} to ${names.get(move.to) ?? move.to}`;
  }).join(', then ');
  return text ? text[0].toUpperCase() + text.slice(1) : 'Already there';
}
