import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MapTab } from './MapTab';
import type { EngineClient } from './client';
import type { NavigationStatus } from './contracts';
import { snapshot } from './test-fixtures';

afterEach(() => { cleanup(); sessionStorage.clear(); });

const profile = {
  schema_version: 2, id: 'area', revision: 5, name: 'Middle Forest III', views: [],
  boundary: { x: 0, y: 0, width: 1000, height: 600 }, zones: [],
  platforms: [
    { id: 'fh1', name: 'Floor', start: { x: 0, y: 500 }, end: { x: 1000, y: 500 } },
    { id: 'fh2', name: 'Level 1 left', start: { x: 100, y: 440 }, end: { x: 300, y: 440 } },
  ],
  ropes: [{ id: 'rope1', name: 'Ladder to Top', start: { x: 700, y: 190 }, end: { x: 700, y: 508 } }],
  links: [],
};

const navigation = {
  stage: 'idle', reason: '', active: false, ready: false, blocker: null, route: null,
  map: { area_id: 'area', revision: 5, home: 'fh1', usable_edges: 1, disabled_edges: {}, nodes: [
    { id: 'fh1', name: 'Floor', kind: 'platform', excluded: false },
    { id: 'rope1', name: 'Ladder to Top', kind: 'rope', excluded: false },
  ] },
} as unknown as NavigationStatus;

const command = vi.fn(async (name: string) => name === 'area_list' ? { areas: [{ id: 'area', name: 'Middle Forest III' }] }
  : name === 'farm_route_map' ? { profile, map_hash: 'a'.repeat(64), farmable: ['fh1', 'fh2'], moves: [] } : { routes: [] });

const view = (kind: string, surface: string | null, feet: [number, number] | null) => <MapTab
  snapshot={snapshot({ navigation, position: { area_id: 'area', area_name: 'Middle Forest III', kind,
    surface_id: surface, feet, reason: 'reading', input_sent: false } })}
  client={{ command } as unknown as EngineClient} disabled={false} />;

it('is the path builder, with where you are and nothing else', async () => {
  render(view('platform', 'fh1', [500, 500]));
  expect(screen.getByRole('heading', { name: 'You are on Floor' })).toBeTruthy();
  await screen.findByRole('region', { name: 'Farming path builder' });
  expect(screen.queryByRole('list', { name: 'Places on this map' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Open full map' })).toBeNull();
  expect(command.mock.calls.map(([name]) => name)).not.toContain('nav_preview');
});

it('tells you to leave a rope before farming', () => {
  render(view('rope', 'rope1', [700, 300]));
  expect(screen.getByRole('heading', { name: "You're on a rope (Ladder to Top); stand on a platform to farm" })).toBeTruthy();
});

it('keeps the last position faded briefly on the builder map instead of blinking', async () => {
  const { container, rerender } = render(view('platform', 'fh1', [500, 500]));
  await screen.findByRole('region', { name: 'Farming path builder' });
  expect(container.querySelector('.path-player:not(.stale)')).toBeTruthy();
  vi.useFakeTimers();
  try {
    rerender(view('unknown', null, null));
    expect(container.querySelector('.path-player.stale')).toBeTruthy();
    await act(async () => { vi.advanceTimersByTime(2100); });
    expect(container.querySelector('.path-player')).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});
