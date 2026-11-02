import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PathBuilder } from './PathBuilder';
import type { EngineClient } from './client';
import type { AreaProfile } from './contracts';
import type { RouteOptions } from './pathPlanning';

afterEach(() => { cleanup(); sessionStorage.clear(); });
const profile = { id: 'map', name: 'Forest', boundary: { x: 0, y: 0, width: 600, height: 400 },
  platforms: ['a', 'b', 'c'].map((id, index) => ({ id, name: `Platform ${id}`, start: { x: index * 150, y: 300 - index * 70 }, end: { x: index * 150 + 100, y: 300 - index * 70 } }))
    .concat([{ id: 'd', name: 'Platform d', start: { x: 480, y: 40 }, end: { x: 580, y: 40 } }]),
  ropes: [], zones: [] } as unknown as AreaProfile;
const hash = 'a'.repeat(64);
// Trusted moves as farm_route_map returns them; d has none, so it is not farmable.
const move = (id: string, kind: string, from: string, to: string, launch: number[], landing: number[]) => ({ id, kind, from, to, launch, landing });
const options: RouteOptions = { farmable: ['a', 'b', 'c'], moves: [
  move('ab', 'jump', 'a', 'b', [100, 300], [150, 230]), move('ba', 'drop', 'b', 'a', [150, 230], [95, 300]),
  move('bc', 'jump', 'b', 'c', [250, 230], [300, 160]), move('cb', 'drop', 'c', 'b', [300, 160], [245, 230])] };
function setup(withOptions?: RouteOptions) {
  const onSelect = vi.fn();
  const command = vi.fn(async (name: string, payload?: Record<string, unknown>) => {
    if (name === 'farm_route_list') return { routes: [] };
    if (name === 'farm_route_save') return { route: { ...(payload!.route as object), revision: 1 } };
    return { route: payload!.route, valid: true, errors: [], legs: [] };
  });
  render(<PathBuilder profile={profile} mapHash={hash} client={{ command } as unknown as EngineClient} disabled={false} onSelect={onSelect} options={withOptions} />);
  return { command, onSelect };
}
const farm = (id: string) => fireEvent.click(screen.getByRole('switch', { name: `Farm on Platform ${id}` }));
const order = () => screen.getByRole('list', { name: 'Farming stops' }).textContent;
function map() {
  const svg = screen.getByRole('img', { name: /Farming circuit map/ });
  // Screen pixels equal map units, so pointer coordinates below are map coordinates.
  svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 600, height: 400, x: 0, y: 0, right: 600, bottom: 400, toJSON: () => ({}) });
  return svg;
}

it('authors, reorders, undoes, saves and validates a three-platform circuit before selection', async () => {
  const { command, onSelect } = setup();
  await waitFor(() => expect(command).toHaveBeenCalledWith('farm_route_list', { area_id: 'map' }));
  farm('a'); farm('b'); farm('c');
  fireEvent.click(screen.getByRole('button', { name: 'Move stop 3 up' }));
  expect(order()).toMatch(/Platform a.*Platform c.*Platform b/);
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
  expect(order()).toMatch(/Platform a.*Platform b.*Platform c/);
  expect(screen.getByRole('button', { name: 'Select for farming' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Check and save path' }));
  await screen.findByText(/Path checked and saved/);
  await screen.findByText(/connections ready/);
  fireEvent.click(screen.getByRole('button', { name: 'Select for farming' }));
  expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ stops: ['a', 'b', 'c'], loop: true, revision: 1 }));
  farm('c');
  expect(onSelect).toHaveBeenLastCalledWith(null);
  expect(screen.getByRole('button', { name: 'Select for farming' }).hasAttribute('disabled')).toBe(true);
});

it('reloads a saved circuit and reports stale geometry without enabling farming', async () => {
  const command = vi.fn(async (name: string) => name === 'farm_route_list' ? { routes: [{ version: 1, revision: 2, id: 'saved', name: 'Old circuit', area_id: 'map', map_hash: 'b'.repeat(64), stops: ['a', 'b'], loop: true }] }
    : { valid: false, errors: ['Map geometry changed'], legs: [] });
  render(<PathBuilder profile={profile} mapHash={hash} client={{ command } as unknown as EngineClient} disabled={false} />);
  fireEvent.click(screen.getByText('Saved paths and editing tools'));
  await screen.findByRole('option', { name: 'Old circuit' });
  fireEvent.change(screen.getByLabelText('Saved path'), { target: { value: 'saved' } });
  fireEvent.click(screen.getByRole('button', { name: 'Check and save path' }));
  await screen.findByText('Map geometry changed');
  expect(screen.getByRole('button', { name: 'Select for farming' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Bind draft to current map' }));
  expect(screen.getByText('Unsaved changes')).toBeTruthy();
});

it('starts from an engine-backed suggestion and never offers a platform without a trusted round trip', () => {
  setup(options);
  fireEvent.click(screen.getByRole('button', { name: /Whole map/ }));
  expect((screen.getByLabelText('Path name') as HTMLInputElement).value).toBe('Whole map');
  // Suggestions choose the order, so the manual order list stays hidden.
  expect(screen.queryByRole('list', { name: 'Farming stops' })).toBeNull();
  expect(screen.getByText(/3 stops, and every trip has a trusted move/)).toBeTruthy();
  expect(screen.getByRole('switch', { name: 'Farm on Platform d' }).hasAttribute('disabled')).toBe(true);
  // Trips name the side the bot leaves from: it lands on b's left end, so c is to its right.
  expect(screen.getByRole('list', { name: 'Trips' }).textContent).toContain('Go right, jump to Platform c');
});

it('draws the stop order with a drag and toggles a platform with a click', () => {
  setup(options);
  const svg = map();
  fireEvent.pointerDown(svg, { clientX: 50, clientY: 300, button: 0, pointerId: 1 });
  for (const [x, y] of [[120, 260], [200, 230], [260, 200], [350, 160], [530, 40]]) fireEvent.pointerMove(svg, { clientX: x, clientY: y, pointerId: 1 });
  fireEvent.pointerUp(svg, { clientX: 530, clientY: 40, pointerId: 1 });
  expect(order()).toMatch(/Platform a.*Platform b.*Platform c/);
  expect(screen.getByText(/Using the order you drew \(3 stops\)\. Skipped Platform d/)).toBeTruthy();
  // A press without movement switches the platform off again.
  fireEvent.pointerDown(svg, { clientX: 200, clientY: 230, button: 0, pointerId: 2 });
  fireEvent.pointerUp(svg, { clientX: 200, clientY: 230, pointerId: 2 });
  expect(order()).not.toMatch(/Platform b/);
  // Clicking a platform without a trusted round trip explains why instead of adding it.
  fireEvent.pointerDown(svg, { clientX: 530, clientY: 40, button: 0, pointerId: 3 });
  fireEvent.pointerUp(svg, { clientX: 530, clientY: 40, pointerId: 3 });
  expect(screen.getByText(/Platform d can't be a farming stop/)).toBeTruthy();
});
