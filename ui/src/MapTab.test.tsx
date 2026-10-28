import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MapTab } from './MapTab';
import type { EngineClient } from './client';
import type { NavigationStatus } from './contracts';
import { snapshot } from './test-fixtures';

afterEach(cleanup);

const profile = {
  schema_version: 2, id: 'area', revision: 5, name: 'Middle Forest III', views: [],
  boundary: { x: 0, y: 0, width: 1000, height: 600 },
  zones: [{ id: 'portal1', kind: 'portal', rect: { x: 400, y: 430, width: 50, height: 70 } }],
  platforms: [
    { id: 'fh1', name: 'Floor', start: { x: 0, y: 500 }, end: { x: 1000, y: 500 } },
    { id: 'fh2', name: 'Level 1 left', start: { x: 100, y: 440 }, end: { x: 300, y: 440 },
      points: [{ x: 100, y: 440 }, { x: 200, y: 420 }, { x: 300, y: 440 }] },
    { id: 'fh3', name: 'Top', start: { x: 600, y: 200 }, end: { x: 800, y: 200 } },
  ],
  ropes: [{ id: 'rope1', name: 'Ladder to Top', start: { x: 700, y: 190 }, end: { x: 700, y: 508 } }],
  links: [],
};

const navigation = {
  stage: 'idle', reason: '', active: false, ready: false, blocker: null, route: null,
  map: { area_id: 'area', revision: 5, home: 'fh1', usable_edges: 4, proven_edges: 1,
    disabled_edges: {}, edges: [{ id: 'm_fh1_fh2', from: 'fh1', to: 'fh2', kind: 'jump', proven: true }],
    nodes: [
      { id: 'fh1', name: 'Floor', kind: 'platform', excluded: false },
      { id: 'fh2', name: 'Level 1 left', kind: 'platform', excluded: false },
      { id: 'fh3', name: 'Top', kind: 'platform', excluded: true },
      { id: 'rope1', name: 'Ladder to Top', kind: 'rope', excluded: false },
    ] },
} as unknown as NavigationStatus;

function setup(surface: string | null = 'fh1') {
  const command = vi.fn(async (name: string) => name === 'area_load' ? { profile } : navigation);
  const onPreview = vi.fn();
  render(<MapTab snapshot={snapshot({ navigation, position: {
    area_id: 'area', kind: surface ? 'platform' : 'unknown', surface_id: surface, feet: [500, 500],
    reason: 'On the floor', input_sent: false } })}
    client={{ command } as unknown as EngineClient} disabled={false}
    act={async operation => { await operation(); }} onPreview={onPreview} />);
  return { command, onPreview };
}

it('draws the whole map with every place named and shows where you are', async () => {
  setup();
  expect(await screen.findByRole('img', { name: 'Map of Middle Forest III' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'You are on Floor' })).toBeTruthy();
  const places = screen.getByRole('list', { name: 'Places on this map' });
  expect(places.textContent).toContain('Top');
  expect(places.textContent).toContain('Level 1 left');
  expect(places.textContent).toContain('Floor · you');
  expect(places.textContent).toContain('Ladder to Top');
  expect(screen.getByText('1 of 4 moves proven. Unproven moves run only on supervised routes; rotation waits until they succeed once.')).toBeTruthy();
});

it('previews a route from your platform to a picked place, never to unreachable ones', async () => {
  const { command, onPreview } = setup();
  fireEvent.click(await screen.findByRole('button', { name: 'Level 1 left' }));
  await waitFor(() => expect(command).toHaveBeenCalledWith('nav_preview', { origin: 'fh1', target: 'fh2' }));
  expect(onPreview).toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Top' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: 'Floor · you' }).hasAttribute('disabled')).toBe(true);
});

it('opens a full-size map and closes it again', async () => {
  setup(null);
  expect(await screen.findByRole('heading', { name: 'Where you are is unknown' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Open full map' }));
  expect(screen.getByRole('dialog', { name: 'Full map of Middle Forest III' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(screen.queryByRole('dialog')).toBeNull();
});
