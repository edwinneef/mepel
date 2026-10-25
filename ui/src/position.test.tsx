import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EngineClient } from './client';
import type { LivePosition, TaughtGeometry } from './contracts';
import { PositionOverlay, PositionPanel } from './PositionPanel';
import { snapshot } from './test-fixtures';

afterEach(() => cleanup());

const geometry: TaughtGeometry = {
  platforms: [{ id: 'walk_p1', start: { x: 30, y: 593 }, end: { x: 1308, y: 593 } }, { id: 'walk_p2', start: { x: 400, y: 445 }, end: { x: 700, y: 445 } }],
  ropes: [], links: [{ id: 'walk_l1', from: 'walk_p1', to: 'walk_p2', kind: 'jump' }],
  boundary: { x: -10, y: 345, width: 1360, height: 290 },
};
const tracked: LivePosition = {
  area_id: 'a'.repeat(32), area_name: 'Floor', kind: 'platform', surface_id: 'floor', feet: [500, 600],
  reason: 'Marker and name tag agree; contact not verified', map: 'Player marker on the taught map',
  canvas: { x: 13, y: 72, width: 183, height: 64 }, marker: [62.5, 22.5], calibrated: true, stale: false,
  calibration: { active: false, pairs: 0, rejected: 0, saved: null }, input_sent: false,
  teaching: { phase: null, geometry: null, samples: 0 },
};

function setup(position: LivePosition | null) {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({ ok: true });
  const refreshAreas = vi.fn(async () => {});
  render(<PositionPanel snapshot={snapshot({ position })} client={client} act={async operation => { await operation(); }}
    disabled={false} areas={[{ id: 'a'.repeat(32), name: 'Floor', revision: 2 }]} refreshAreas={refreshAreas} />);
  return { command, refreshAreas };
}

it('tracks a saved map or starts a new one from this screen', async () => {
  const { command, refreshAreas } = setup(null);
  fireEvent.change(screen.getByLabelText('Saved map'), { target: { value: 'a'.repeat(32) } });
  fireEvent.click(screen.getByRole('button', { name: 'Track position' }));
  expect(command).toHaveBeenCalledWith('position_start', { area_id: 'a'.repeat(32) });
  fireEvent.change(screen.getByLabelText('Map name'), { target: { value: 'Ant Tunnel' } });
  fireEvent.click(screen.getByRole('button', { name: 'Teach a new map' }));
  await waitFor(() => expect(refreshAreas).toHaveBeenCalled());
  expect(command).toHaveBeenCalledWith('teach_new_area', { name: 'Ant Tunnel' });
});

it('walks through teaching: start, record, finish, save', async () => {
  const { command } = setup(tracked);
  expect(screen.getByText(/On floor · contact not verified/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Teach this map' }));
  expect(command).toHaveBeenCalledWith('teach_begin', {});
  cleanup();
  const recording = setup({ ...tracked, teaching: { phase: 'recording', geometry, samples: 120 } });
  expect(screen.getByText('Step 2 of 2 · Recording: 2 platforms · 0 ropes · 1 links')).toBeTruthy();
  expect(screen.getByRole('img', { name: 'Learned map' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Finish' }));
  expect(recording.command).toHaveBeenCalledWith('teach_finish', {});
  cleanup();
  const review = setup({ ...tracked, teaching: { phase: 'review', geometry, samples: 0 } });
  fireEvent.click(screen.getByRole('button', { name: 'Save map' }));
  await waitFor(() => expect(review.command).toHaveBeenCalledWith('teach_save'));
});

it('shows calibration progress while teaching an uncalibrated map', () => {
  setup({ ...tracked, calibration: { active: true, pairs: 7, rejected: 0, saved: null }, teaching: { phase: 'calibrating', geometry: null, samples: 0 } });
  expect(screen.getByText('Step 1 of 2 · Walk left and right along one floor · 7 / 20')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Recalibrate' }).hasAttribute('disabled')).toBe(true);
});

it('overlays the marker, or the unknown reason without a marker', () => {
  const { container, rerender } = render(<svg><PositionOverlay position={tracked} /></svg>);
  const marker = container.querySelector('circle.position-marker');
  expect(marker?.getAttribute('cx')).toBe('75.5');
  expect(marker?.getAttribute('cy')).toBe('94.5');
  rerender(<svg><PositionOverlay position={{ ...tracked, kind: 'unknown', surface_id: null, marker: null, canvas: null, reason: 'Position stale: no processed frame for 700 ms', stale: true }} /></svg>);
  expect(container.querySelector('circle')).toBeNull();
  expect(screen.getByText('Position unknown · Position stale: no processed frame for 700 ms')).toBeTruthy();
});
