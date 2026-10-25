import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EngineClient } from './client';
import type { LivePosition } from './contracts';
import { PositionOverlay, PositionPanel } from './PositionPanel';
import { snapshot } from './test-fixtures';

afterEach(() => cleanup());

const tracked: LivePosition = {
  area_id: 'a'.repeat(32), area_name: 'Floor', kind: 'platform', surface_id: 'floor', feet: [500, 600],
  reason: 'Marker and name tag agree; contact not verified', map: 'Player marker on the taught map',
  canvas: { x: 13, y: 72, width: 183, height: 64 }, marker: [62.5, 22.5], calibrated: true, stale: false,
  calibration: { active: true, pairs: 12, rejected: 1, saved: null }, input_sent: false,
};

function setup(position: LivePosition | null) {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({ ok: true });
  render(<PositionPanel snapshot={snapshot({ position })} client={client} act={async operation => { await operation(); }}
    disabled={false} areas={[{ id: 'a'.repeat(32), name: 'Floor', revision: 2 }]} />);
  return command;
}

it('starts read-only tracking for the chosen saved area', () => {
  const command = setup(null);
  expect(screen.getByRole('button', { name: 'Stop tracking' }).hasAttribute('disabled')).toBe(true);
  fireEvent.change(screen.getByLabelText('Track area'), { target: { value: 'a'.repeat(32) } });
  fireEvent.click(screen.getByRole('button', { name: 'Track position' }));
  expect(command).toHaveBeenCalledWith('position_start', { area_id: 'a'.repeat(32) });
});

it('finishes or cancels walk calibration and shows the platform without claiming contact', () => {
  const command = setup(tracked);
  expect(screen.getByText(/On floor · contact not verified/)).toBeTruthy();
  expect(screen.getByText('12 pairs collected · 1 frames without registration')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Finish and save' }));
  expect(command).toHaveBeenCalledWith('walk_calibration_finish', {});
  fireEvent.click(screen.getByRole('button', { name: 'Cancel calibration' }));
  expect(command).toHaveBeenCalledWith('walk_calibration_cancel', {});
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
