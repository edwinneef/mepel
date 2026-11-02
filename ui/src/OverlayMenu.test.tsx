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

it('starts only the chosen looping revision with the displayed duration', () => {
  const calls: unknown[] = [];
  const route = { version: 1 as const, revision: 2, id: 'lower-loop', name: 'Lower loop',
    area_id: 'area', map_hash: 'a'.repeat(64), stops: ['a', 'b'], loop: true };
  render(<OverlayMenu s={{ position: { area_id: 'area' } } as never} status="OFF"
    game={{ x: 0, y: 0, width: 600, height: 400 }} layers={false} attackRange={false} names={false}
    setLayers={() => {}} setAttackRange={() => {}} setNames={() => {}} batch={{ running: false }}
    canBatch paths={{ state: 'ready', names: ['Lower loop'], routes: [route] }}
    onStart={(...args) => calls.push(args)} onStop={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  const start = screen.getByRole('button', { name: 'Start run' }) as HTMLButtonElement;
  expect(start.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Farming circuit'), { target: { value: 'lower-loop' } });
  expect(start.disabled).toBe(false);
  fireEvent.click(start);
  fireEvent.change(screen.getByLabelText('Run duration'), { target: { value: '15' } });
  fireEvent.click(start);
  expect(calls).toEqual([
    ['learn', { id: 'lower-loop', revision: 2 }, 1],
    ['learn', { id: 'lower-loop', revision: 2 }, 15],
  ]);
  cleanup();
});

it('keeps one status line in place as messages come and go, so the menu height holds', () => {
  const props = { s: null, status: 'OFF', game: { x: 0, y: 0, width: 600, height: 400 }, layers: false,
    attackRange: false, names: false, setLayers: () => {}, setAttackRange: () => {}, setNames: () => {},
    canBatch: false, onStart: () => {}, onStop: () => {} };
  const view = render(<OverlayMenu {...props} batch={{ running: false }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  const rows = () => view.container.querySelectorAll('.overlay-menu > p').length;
  const before = rows();
  view.rerender(<OverlayMenu {...props} batch={{ running: false }} startBlocker="Open the browser dashboard" />);
  expect(rows()).toBe(before);
  expect(screen.getByRole('status').textContent).toBe('Open the browser dashboard');
  view.rerender(<OverlayMenu {...props} batch={{ running: true, line: 'Starting one guarded batch' }} />);
  expect(rows()).toBe(before);
  expect(screen.getByRole('status').className).toContain('overlay-menu-line');
  cleanup();
});
