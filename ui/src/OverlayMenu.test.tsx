import { expect, it } from 'vitest';
import { menuPlacement } from './OverlayMenu';

const samples = (game: { x: number; y: number; width: number; height: number }) =>
  [.05, .5, .95].flatMap(fx => [.05, .5, .95].map(fy => ({ x: game.x + game.width * fx, y: game.y + game.height * fy })));

it('places the menu beside the game view, never over it', () => {
  // Live: over the game's top-right the menu covered an engine coverage sample point.
  const game = { x: 13, y: 41, width: 1366, height: 768 };
  expect(menuPlacement(game, { width: 2560, height: 1440 })).toEqual({ left: 1387, top: 41 });
  expect(menuPlacement({ ...game, x: 1300 }, { width: 2560, height: 1440 }).left)
    .toBeLessThan(2560 - 236);
  expect(menuPlacement({ x: 1000, y: 0, width: 1366, height: 768 }, { width: 2400, height: 900 }))
    .toEqual({ left: 756, top: 0 });  // no room on the right: to the left
});

it('inside a full-screen game view, avoids every coverage sample point', () => {
  const game = { x: 0, y: 0, width: 1366, height: 768 };
  const { left, top } = menuPlacement(game, { width: 1366, height: 768 });
  for (const point of samples(game)) {
    const inside = point.x >= left && point.x < left + 236 && point.y >= top && point.y < top + 250;
    expect(inside).toBe(false);
  }
});
