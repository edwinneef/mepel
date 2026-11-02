import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PathBuilder } from './PathBuilder';
import type { EngineClient } from './client';
import type { AreaProfile } from './contracts';

afterEach(() => { cleanup(); sessionStorage.clear(); });
const profile = { id: 'map', name: 'Forest', boundary: { x: 0, y: 0, width: 600, height: 400 },
  platforms: ['a', 'b', 'c'].map((id, index) => ({ id, name: `Platform ${id}`, start: { x: index * 150, y: 300 - index * 70 }, end: { x: index * 150 + 100, y: 300 - index * 70 } })),
  ropes: [], zones: [] } as unknown as AreaProfile;
const hash = 'a'.repeat(64);
function setup() {
  const onSelect = vi.fn();
  const command = vi.fn(async (name: string, payload?: Record<string, unknown>) => {
    if (name === 'farm_route_list') return { routes: [] };
    if (name === 'farm_route_save') return { route: { ...(payload!.route as object), revision: 1 } };
    return { route: payload!.route, valid: true, errors: [], legs: [] };
  });
  render(<PathBuilder profile={profile} mapHash={hash} client={{ command } as unknown as EngineClient} disabled={false} onSelect={onSelect} />);
  return { command, onSelect };
}
function add(id: string) { fireEvent.change(screen.getByLabelText('Add a platform'), { target: { value: id } }); }
it('authors, reorders, undoes, saves and validates a three-platform circuit before selection', async () => {
  const { command, onSelect } = setup();
  await waitFor(() => expect(command).toHaveBeenCalledWith('farm_route_list', { area_id: 'map' }));
  fireEvent.click(screen.getByText('Saved paths and editing tools'));
  add('a'); add('b'); add('c');
  fireEvent.click(screen.getByRole('button', { name: 'Move stop 3 up' }));
  expect(screen.getByRole('list', { name: 'Farming stops' }).textContent).toMatch(/Platform a.*Platform c.*Platform b/);
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
  expect(screen.getByRole('list', { name: 'Farming stops' }).textContent).toMatch(/Platform a.*Platform b.*Platform c/);
  expect(screen.getByRole('button', { name: 'Select for farming' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Check and save path' }));
  await screen.findByText(/Path checked and saved/);
  await screen.findByText(/connections ready/);
  fireEvent.click(screen.getByRole('button', { name: 'Select for farming' }));
  expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ stops: ['a', 'b', 'c'], loop: true, revision: 1 }));
  add('a');
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


