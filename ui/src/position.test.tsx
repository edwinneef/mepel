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
  calibration: { active: false, pairs: 0, rejected: 0, saved: null }, input_sent: false,
};

function setup(position: LivePosition | null) {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({ ok: true });
  const refreshAreas = vi.fn(async () => {});
  const props = { snapshot: snapshot({ position }), client, act: async (operation: () => Promise<unknown>) => { await operation(); },
    disabled: false, areas: [{ id: 'a'.repeat(32), name: 'Floor', revision: 2 }], refreshAreas };
  return { command, refreshAreas, props, ...render(<PositionPanel {...props} />) };
}

it('tracks or switches a saved map without starting gameplay', () => {
  const { command, props, rerender } = setup(null);
  fireEvent.change(screen.getByLabelText('Saved map'), { target: { value: 'a'.repeat(32) } });
  fireEvent.click(screen.getByRole('button', { name: 'Track selected map' }));
  expect(command).toHaveBeenCalledWith('position_start', { area_id: 'a'.repeat(32) });
  rerender(<PositionPanel {...props} snapshot={snapshot({ position: tracked })} />);
  fireEvent.click(screen.getByRole('button', { name: 'Stop tracking' }));
  expect(command).toHaveBeenCalledWith('position_stop', {});
  expect(screen.queryByRole('button', { name: /Teach/ })).toBeNull();
});

it('tells the operator to import a map while the engine is stopped', () => {
  setup(null);
  expect(screen.getByText(/stop the engine and run/).textContent).toContain('maplebot import-map "<map name>"');
});

it('starts, finishes and cancels walk calibration', () => {
  const { command, props, rerender } = setup({ ...tracked, calibrated: false });
  expect(screen.getByText('Walk calibration needed')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Start walk calibration' }));
  expect(command).toHaveBeenCalledWith('walk_calibration_begin', {});
  rerender(<PositionPanel {...props} snapshot={snapshot({ position: { ...tracked,
    calibration: { active: true, pairs: 7, rejected: 1, saved: null } } })} />);
  expect(screen.getByText(/7 samples \(1 rejected\)/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Finish calibration' }));
  expect(command).toHaveBeenCalledWith('walk_calibration_finish', {});
  fireEvent.click(screen.getByRole('button', { name: 'Cancel calibration' }));
  expect(command).toHaveBeenCalledWith('walk_calibration_cancel', {});
});

it('offers a reversible session-only supplement only in capture-only observation', () => {
  const supplemented = { ...tracked, supplement: { available: true, enabled: false,
    reason: 'Off', platform: null } };
  const { command, props, rerender } = setup(supplemented);
  rerender(<PositionPanel {...props} snapshot={{ ...props.snapshot, capture_only: true, mode: 'capture' }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Observe middle ledge' }));
  expect(command).toHaveBeenCalledWith('position_supplement', { enabled: true });
  rerender(<PositionPanel {...props} snapshot={{ ...props.snapshot, capture_only: true, mode: 'capture',
    position: { ...supplemented, supplement: { ...supplemented.supplement, enabled: true } } }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Stop observing middle ledge' }));
  expect(command).toHaveBeenCalledWith('position_supplement', { enabled: false });
  rerender(<PositionPanel {...props} snapshot={{ ...props.snapshot, capture_only: false }} />);
  expect(screen.queryByRole('button', { name: 'Observe middle ledge' })).toBeNull();
});

it('overlays a current marker or an explicit unknown reason', () => {
  const { container, rerender } = render(<svg><PositionOverlay position={tracked} /></svg>);
  const marker = container.querySelector('circle.position-marker');
  expect(marker?.getAttribute('cx')).toBe('75.5');
  expect(marker?.getAttribute('cy')).toBe('94.5');
  rerender(<svg><PositionOverlay position={{ ...tracked, kind: 'unknown', surface_id: null, marker: null,
    reason: 'Position stale: no processed frame for 700 ms', stale: true }} /></svg>);
  expect(container.querySelector('circle')).toBeNull();
  expect(screen.getByText('Position unknown · Position stale: no processed frame for 700 ms')).toBeTruthy();
});
