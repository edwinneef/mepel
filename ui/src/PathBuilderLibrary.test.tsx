import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PathBuilderLibrary } from './PathBuilderLibrary';
import type { EngineClient } from './client';

afterEach(() => { cleanup(); sessionStorage.clear(); });
const profile = (id: string) => ({ id, name: id, boundary: { x: 0, y: 0, width: 600, height: 400 }, zones: [], ropes: [],
  platforms: [{ id: 'a', name: 'Platform a', start: { x: 0, y: 300 }, end: { x: 100, y: 300 } }] });

it('loads saved maps and opens the current map without any button press', async () => {
  const command = vi.fn(async (name: string, payload?: Record<string, unknown>) => {
    if (name === 'area_list') return { areas: [{ id: 'here', name: 'Snail Hunting Ground III' }, { id: 'other', name: 'Henesys' }] };
    if (name === 'farm_route_map') return { profile: profile(payload!.area_id as string), map_hash: 'a'.repeat(64), farmable: ['a'], moves: [] };
    return { routes: [] };
  });
  render(<PathBuilderLibrary client={{ command } as unknown as EngineClient} disabled={false} initialArea="here" />);
  await screen.findByRole('region', { name: 'Farming path builder' });
  expect(command).toHaveBeenCalledWith('area_list');
  expect(command).toHaveBeenCalledWith('farm_route_map', { area_id: 'here' });
  expect(screen.queryByRole('button', { name: /Load saved farming maps|Open path builder/ })).toBeNull();
  fireEvent.change(screen.getByLabelText('Map for path builder'), { target: { value: 'other' } });
  await waitFor(() => expect(command).toHaveBeenCalledWith('farm_route_map', { area_id: 'other' }));
});

it('waits while the bot runs, then loads by itself', async () => {
  const command = vi.fn(async (name: string) => name === 'area_list' ? { areas: [] } : { routes: [] });
  const view = render(<PathBuilderLibrary client={{ command } as unknown as EngineClient} disabled initialArea="here" />);
  expect(command).not.toHaveBeenCalled();
  view.rerender(<PathBuilderLibrary client={{ command } as unknown as EngineClient} disabled={false} initialArea="here" />);
  await waitFor(() => expect(command).toHaveBeenCalledWith('area_list'));
});

it('asks for the map only after the map list, and retries a busy refusal by itself', async () => {
  let refusals = 1;
  const order: string[] = [];
  const command = vi.fn(async (name: string, payload?: Record<string, unknown>) => {
    order.push(name);
    if (name === 'area_list') return { areas: [{ id: 'here', name: 'Tree Dungeon' }] };
    if (name === 'farm_route_map') {
      if (refusals-- > 0) throw new Error('Wait for the current operation to finish. Stop remains available.');
      return { profile: profile(payload!.area_id as string), map_hash: 'a'.repeat(64), farmable: ['a'], moves: [] };
    }
    return { routes: [] };
  });
  render(<PathBuilderLibrary client={{ command } as unknown as EngineClient} disabled={false} initialArea="here" />);
  await screen.findByRole('region', { name: 'Farming path builder' }, { timeout: 3000 });
  expect(order.slice(0, 2)).toEqual(['area_list', 'farm_route_map']);
  expect(order.filter(name => name === 'farm_route_map')).toHaveLength(2);
  expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
});
