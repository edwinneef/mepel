import { render, fireEvent, screen, cleanup } from '@testing-library/react';
import { OverlayMenu } from './OverlayMenu';
import { expect, it } from 'vitest';
import { DOCK_SCALE, FOLDED_HEIGHT, batchReport, dockPlacement, menuPlacement, pathSummary } from './OverlayMenu';

const samples = (game: { x: number; y: number; width: number; height: number }) =>
  [.05, .5, .95].flatMap(fx => [.05, .5, .95].map(fy => ({ x: game.x + game.width * fx, y: game.y + game.height * fy })));

it('places the menu beside the game view, never over it', () => {
  // Live: over the game's top-right the menu covered an engine coverage sample point.
  const game = { x: 13, y: 41, width: 1366, height: 768 };
  expect(menuPlacement(game, { width: 2560, height: 1440 })).toEqual({ left: 1387, top: 41 });
  expect(menuPlacement({ ...game, x: 1300 }, { width: 2560, height: 1440 }).left)
    .toBeLessThan(2560 - 300);
  expect(menuPlacement({ x: 1000, y: 0, width: 1366, height: 768 }, { width: 2400, height: 900 }))
    .toEqual({ left: 692, top: 0 });  // no room on the right: to the left
});

it('inside a full-screen game view, avoids every coverage sample point', () => {
  const game = { x: 0, y: 0, width: 1366, height: 768 };
  const { left, top } = menuPlacement(game, { width: 1366, height: 768 });
  for (const point of samples(game)) {
    const inside = point.x >= left && point.x < left + 300 && point.y >= top && point.y < top + 250;
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
  fireEvent.click(screen.getByRole('button', { name: 'Enemies' }));
  expect(calls).toEqual([true]);
  expect(screen.getByRole('button', { name: 'Map lines' }).getAttribute('aria-pressed')).toBe('false');
  expect(screen.getByRole('button', { name: 'Attack range' })).toBeTruthy();
  cleanup();
});

it('says in one line whether the map has a saved path', () => {
  expect(pathSummary({ state: 'ready', names: ['Lower loop'] }, null).text).toBe('map not recognised');
  expect(pathSummary({ state: 'ready', names: [] }, 'area')).toMatchObject({ tone: 'none', text: 'none on this map' });
  expect(pathSummary({ state: 'ready', names: ['Lower loop', 'Left side'] }, 'area')).toMatchObject({
    tone: 'ready', text: 'Lower loop +1', title: expect.stringContaining('Lower loop, Left side') });
  render(<OverlayMenu s={{ position: { area_id: 'area' } } as never} status="OFF" game={{ x: 0, y: 0, width: 600, height: 400 }}
    layers={false} attackRange={false} names={false} setLayers={() => {}} setAttackRange={() => {}} setNames={() => {}}
    batch={{ running: false }} canBatch onStart={() => {}} onStop={() => {}} paths={{ state: 'ready', names: [], routes: [] }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  expect(screen.getByText('No saved loop on this map. Build one in Maps.')).toBeTruthy();
  expect(screen.getByText("Can't start: this map has no saved loop")).toBeTruthy();
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
  const start = screen.getByRole('button', { name: 'Start' }) as HTMLButtonElement;
  expect(start.disabled).toBe(true);
  expect(screen.queryByRole('combobox')).toBeNull();  // native popups never open in the widget
  fireEvent.click(screen.getByRole('button', { name: 'Next loop' }));
  expect(screen.getByText('Lower loop · r2')).toBeTruthy();
  expect(start.disabled).toBe(false);
  fireEvent.click(start);
  fireEvent.click(screen.getByRole('radio', { name: '15 min' }));
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
  const rows = () => view.container.querySelectorAll('.w-body > p').length;
  const before = rows();
  view.rerender(<OverlayMenu {...props} batch={{ running: false }} startBlocker="Open the browser dashboard" />);
  expect(rows()).toBe(before);
  expect(screen.getByRole('status').textContent).toBe('Cannot start yetOpen the browser dashboard');
  view.rerender(<OverlayMenu {...props} batch={{ running: true, line: 'Starting one guarded batch' }} />);
  expect(rows()).toBe(before);
  expect(screen.getByRole('status').textContent).toBe('ProgressStarting one guarded batch');
  cleanup();
});

it('shows the recognised map name above the saved paths', () => {
  const props = { status: 'OFF', game: { x: 0, y: 0, width: 600, height: 400 }, layers: false,
    attackRange: false, names: false, setLayers: () => {}, setAttackRange: () => {}, setNames: () => {},
    canBatch: false, onStart: () => {}, onStop: () => {}, batch: { running: false } };
  const view = render(<OverlayMenu {...props} s={null} />);
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  expect(screen.getByText('Map not recognised')).toBeTruthy();
  view.rerender(<OverlayMenu {...props} s={{ position: { area_id: 'a', area_name: 'Tree Dungeon, Forest Up North I', kind: 'platform' } } as never} />);
  expect(screen.getByText('Tree Dungeon, Forest Up North I')).toBeTruthy();
  cleanup();
});

it('explains a failed run in full: why, how the engine stopped and what to do', () => {
  const output = ['Starting', JSON.stringify({ outcome: 'failure', error: 'Game lost focus',
    stop: { code: 'FOCUS_LOST', message: 'MapleStory is not focused; input released' },
    stop_error: null, proven_after: 3, misses: [['fh1', 'fh2']] }), 'Control returned to operator.'].join('\n');
  expect(batchReport({ running: false, code: 1, output })).toEqual({ tone: 'fail', headline: 'Run failed',
    detail: ['Why: Game lost focus', 'Engine stop (FOCUS_LOST): MapleStory is not focused; input released',
      '3 moves proven · 1 missed move landed safely',
      'Keys released, clip saved. Move to safety; no automatic retry.'].join('\n') });
  expect(batchReport({ running: false, code: 1, output: '{"blocked": "Stand still first", "input_sent": false}' }))
    .toEqual({ tone: 'fail', headline: 'Not started · no keys sent', detail: 'Stand still first' });
  expect(batchReport({ running: false, code: 0, output: '{"outcome": "functional_success", "proven_after": 2}' }))
    .toEqual({ tone: 'ok', headline: 'Finished the full session', detail: '2 moves proven' });
});

it('docks bottom-left inside the game, clear of every coverage sample point, and grows upward', () => {
  for (const game of [{ x: 13, y: 41, width: 1366, height: 768 }, { x: 0, y: 0, width: 1024, height: 768 },
    { x: 200, y: 120, width: 1920, height: 1080 }]) {
    const viewport = { width: 2560, height: 1440 };
    const dock = dockPlacement(game, viewport)!;
    expect(dock).not.toBeNull();
    // The visual rect, scaled from its bottom-left corner, stays inside the game's left half.
    expect(dock.left).toBe(game.x + 8);
    expect(dock.bottom).toBe(game.y + game.height - 8);
    expect(dock.left + 300 * DOCK_SCALE).toBeLessThan(game.x + game.width / 2);
    expect(dock.bottom - dock.openHeight * DOCK_SCALE).toBeGreaterThan(game.y);
    expect(dock.openHeight).toBe(360);
  }
  expect(dockPlacement({ x: 0, y: 0, width: 400, height: 300 }, { width: 1920, height: 1080 })).toBeNull();
  const props = { s: null, status: 'OFF', layers: false, attackRange: false, names: false, setLayers: () => {},
    setAttackRange: () => {}, setNames: () => {}, canBatch: false, onStart: () => {}, onStop: () => {}, batch: { running: false } };
  render(<OverlayMenu {...props} game={{ x: 0, y: 0, width: 1024, height: 768 }} />);
  const menu = screen.getByLabelText('Bot menu');
  expect(menu.className).toContain('is-docked');
  const edge = () => parseInt(menu.style.top) + parseInt(menu.style.height);
  const dock = dockPlacement({ x: 0, y: 0, width: 1024, height: 768 }, { width: innerWidth, height: innerHeight })!;
  expect(menu.style.height).toBe(`${FOLDED_HEIGHT}px`);
  expect(edge()).toBe(dock.bottom);  // the folded bar sits on the dock's bottom edge
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
  expect(parseInt(menu.style.height)).toBe(dock.openHeight);
  expect(edge()).toBe(dock.bottom);  // opening grows it upward; the bottom edge stays put
  // A docked widget cannot be dragged: dragging dropped its scale and dock.
  const head = menu.querySelector('header')!;
  fireEvent.pointerDown(head, { button: 0, clientX: 20, clientY: 700, pointerId: 1 });
  fireEvent.pointerMove(head, { clientX: 400, clientY: 300, pointerId: 1 });
  expect(menu.className).toContain('is-docked');
  expect(edge()).toBe(dock.bottom);
  cleanup();
});
