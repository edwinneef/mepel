import { render, fireEvent, screen, cleanup } from '@testing-library/react';
import { OverlayMenu } from './OverlayMenu';
import { expect, it } from 'vitest';
import { menuPlacement, pathSummary } from './OverlayMenu';

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

it('keeps Stop visible when folded and aligns independently labelled layer controls', () => {
  const calls: boolean[] = [];
  render(<OverlayMenu s={null} status="OFF" game={{ x: 0, y: 0, width: 600, height: 400 }}
    layers={false} attackRange={false} names={false} setLayers={v => calls.push(v)}
    setAttackRange={() => {}} setNames={() => {}} batch={{ running: false }} canBatch={false}
    onStart={() => {}} onStop={() => {}} />);
  expect(screen.getByRole('button', { name: 'Stop (F8)' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Enemies' }));
  expect(calls).toEqual([true]);
  expect(screen.getByRole('checkbox', { name: 'Map' })).toBeTruthy();
  expect(screen.getByRole('checkbox', { name: 'Range' })).toBeTruthy();
  cleanup();
});

it('says in one line whether the map has a saved path', () => {
  expect(pathSummary({ state: 'ready', names: ['Lower loop'] }, null).text).toBe('map not recognised');
  expect(pathSummary({ state: 'ready', names: [] }, 'area')).toMatchObject({ tone: 'none', text: 'none on this map' });
  expect(pathSummary({ state: 'ready', names: ['Lower loop', 'Left side'] }, 'area')).toMatchObject({
    tone: 'ready', text: 'Lower loop +1', title: expect.stringContaining('Lower loop, Left side') });
  render(<OverlayMenu s={{ position: { area_id: 'area' } } as never} status="OFF" game={{ x: 0, y: 0, width: 600, height: 400 }}
    layers={false} attackRange={false} names={false} setLayers={() => {}} setAttackRange={() => {}} setNames={() => {}}
    batch={{ running: false }} canBatch={false} onStart={() => {}} onStop={() => {}} paths={{ state: 'ready', names: ['Lower loop'] }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  expect(screen.getByTitle(/1 saved for this map: Lower loop/).textContent).toBe('PathLower loop');
  cleanup();
});
