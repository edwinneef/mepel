import { expect, it } from 'vitest';
import type { AreaProfile } from './contracts';
import { planRoute, platformAt, shortestOrder, suggestions } from './pathPlanning';

const platform = (id: string, x1: number, x2: number, y: number) => ({ id, name: id, start: { x: x1, y }, end: { x: x2, y } });
const profile = { id: 'm', boundary: { x: 0, y: 0, width: 1200, height: 600 }, zones: [], ropes: [],
  platforms: [platform('floor', 30, 1170, 545), platform('mid', 460, 740, 400), platform('left', 70, 360, 425)] } as unknown as AreaProfile;
const m = (id: string, kind: string, from: string, to: string, launch: number[], landing: number[]) => ({ id, kind, from, to, launch, landing });
// The floor can be left at either end of mid: dropping off the left or the right end.
const moves = [m('up', 'climb', 'floor', 'left', [210, 545], [210, 425]), m('across', 'jump', 'left', 'mid', [360, 425], [460, 400]),
  m('offLeft', 'drop', 'mid', 'floor', [460, 400], [445, 545]), m('offRight', 'drop', 'mid', 'floor', [740, 400], [755, 545]),
  m('down', 'drop', 'left', 'floor', [70, 425], [55, 545])];

it('leaves a platform from the exit nearest to where the bot stands', () => {
  // Arriving on mid at its left end (x 460), the left-end drop is nearest.
  const legs = planRoute(profile, moves, ['left', 'mid', 'floor'], false);
  expect(legs.map(leg => leg.moves?.map(item => item.id))).toEqual([['across'], ['offLeft']]);
  expect(legs[1].end).toEqual([445, 545]);
});

it('reports a trip without a trusted move instead of inventing one', () => {
  const legs = planRoute(profile, moves.filter(item => item.id !== 'up'), ['floor', 'mid'], false);
  expect(legs[0].moves).toBeNull();
});

it('orders stops by fewest moves from the first stop and offers only loops that plan', () => {
  expect(shortestOrder(profile, moves, ['floor', 'mid', 'left'])).toEqual(['floor', 'left', 'mid']);
  const ideas = suggestions(profile, { farmable: ['floor', 'mid', 'left'], moves });
  expect(ideas[0]).toMatchObject({ id: 'all', stops: ['floor', 'left', 'mid'] });
  expect(ideas.every(idea => planRoute(profile, moves, idea.stops, true).every(leg => leg.moves))).toBe(true);
  expect(suggestions(profile, { farmable: ['floor'], moves })).toEqual([]);
});

it('finds the platform under a point within reach only', () => {
  expect(platformAt(profile, { x: 600, y: 410 }, 20)).toBe('mid');
  expect(platformAt(profile, { x: 600, y: 470 }, 20)).toBeNull();
});

it('offers a zig-zag loop on a tall map where nearest-first would need one overlong trip home', () => {
  // Twelve stacked levels joined only to their neighbours: going home from the top takes 11 moves.
  const levels = Array.from({ length: 12 }, (_, i) => platform(`L${i + 1}`, 100, 300, 1200 - i * 100));
  const tall = { ...profile, boundary: { x: 0, y: 0, width: 400, height: 1300 }, platforms: levels } as unknown as AreaProfile;
  const climbs = levels.slice(1).flatMap((p, i) => [m(`u${i}`, 'climb', levels[i].id, p.id, [200, levels[i].start.y], [200, p.start.y]),
    m(`d${i}`, 'drop', p.id, levels[i].id, [200, p.start.y], [200, levels[i].start.y])]);
  const whole = suggestions(tall, { farmable: levels.map(p => p.id), moves: climbs }).find(idea => idea.id === 'all');
  expect(whole?.stops).toEqual(['L1', 'L3', 'L5', 'L7', 'L9', 'L11', 'L12', 'L10', 'L8', 'L6', 'L4', 'L2']);
  expect(planRoute(tall, climbs, whole!.stops, true).every(leg => leg.moves && leg.moves.length <= 2)).toBe(true);
});
