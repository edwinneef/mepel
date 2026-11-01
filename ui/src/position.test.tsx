import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EngineClient } from './client';
import type { LivePosition } from './contracts';
import { PositionOverlay, PositionPanel } from './PositionPanel';
import { snapshot } from './test-fixtures';

afterEach(() => { cleanup(); sessionStorage.clear(); });

it('shows automatic uncertainty without offering calibration or implying gameplay readiness', () => {
  const { command } = setup({ ...tracked, kind: 'unknown', surface_id: null,
    map_alignment: { mode: 'automatic', state: 'uncertain', precision_verified: false,
      uncertainty_px: 16, reason: 'Absolute precision awaits validation' } });
  expect(screen.getByRole('heading', { name: 'Check map' })).toBeTruthy();
  expect(screen.getByText(/No walking calibration or route teaching is needed/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Start walk calibration|Recalibrate/ })).toBeNull();
  expect((screen.getByRole('button', { name: 'Confirm map' }) as HTMLButtonElement).disabled).toBe(true);
  expect(command).not.toHaveBeenCalled();
});

const tracked: LivePosition = {
  area_id: 'a'.repeat(32), area_name: 'Floor', kind: 'platform', surface_id: 'floor', feet: [500, 600],
  reason: 'Marker and name tag agree; contact not verified', map: 'Player marker on the taught map',
  canvas: { x: 13, y: 72, width: 183, height: 64 }, marker: [62.5, 22.5], calibrated: true, stale: false,
  captured_at: Date.now() / 1000,
  calibration: { active: false, pairs: 0, rejected: 0, saved: null }, input_sent: false,
};

function setup(position: LivePosition | null) {
  const capturedAt = Date.now() / 1000;
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({ ok: true });
  const refreshAreas = vi.fn(async () => {});
  const props = { snapshot: snapshot({ position: position && { ...position, captured_at: capturedAt } }), client, act: async (operation: () => Promise<unknown>) => { await operation(); },
    image: { url: 'map.png', width: 1024, height: 768, key: 'test-session:1', sourceId: 'test-source', capturedAt },
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

it('waits without offering walking calibration or terrain selection', () => {
  const { command } = setup({ ...tracked, calibrated: false });
  expect(screen.getByRole('status').textContent).toContain('Waiting for passive alignment');
  expect(screen.queryByRole('button', { name: /calibrat|Teach|Finish/ })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm map' }));
  expect(command).not.toHaveBeenCalled();
});

it('confirms only the map, retains it across panel remounts and never starts gameplay', () => {
  const { command, props, unmount } = setup(tracked);
  expect(screen.getByRole('img', { name: 'Estimated player spot' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm map' }));
  expect(screen.getByRole('heading', { name: 'Map confirmed' })).toBeTruthy();
  expect(props.snapshot.readiness.combat.ready).toBe(false);
  expect(command).not.toHaveBeenCalled();
  unmount();
  render(<PositionPanel {...props} />);
  expect(screen.getByRole('heading', { name: 'Map confirmed' })).toBeTruthy();
});

it('returns a wrong map to an empty saved-map choice without sending keys', () => {
  const { command } = setup(tracked);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm map' }));
  fireEvent.click(screen.getByRole('button', { name: 'Wrong map' }));
  expect((screen.getByLabelText('Saved map') as HTMLSelectElement).value).toBe('');
  expect(sessionStorage.getItem('maple-map-confirmation')).toBeNull();
  expect(command).not.toHaveBeenCalled();
});

it.each(['session', 'source', 'revision', 'map'] as const)('invalidates confirmation after a %s change', change => {
  const { props, rerender } = setup(tracked);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm map' }));
  rerender(<PositionPanel {...props}
    areas={change === 'revision' ? [{ ...props.areas[0], revision: 3 }] : props.areas}
    snapshot={{ ...props.snapshot,
      session_id: change === 'session' ? 'next-session' : props.snapshot.session_id,
      frame: { ...props.snapshot.frame, source_id: change === 'source' ? 'next-source' : props.snapshot.frame.source_id },
      catalog: change === 'map' ? { active_map: 'Another map' } : props.snapshot.catalog,
    }} />);
  expect(screen.getByRole('heading', { name: 'Check map' })).toBeTruthy();
});

it.each(['stale', 'provisional', 'uncertain', 'mismatched picture'] as const)('refuses a %s position without changing readiness', reason => {
  const { command, props, rerender } = setup(tracked);
  const position = { ...tracked,
    stale: reason === 'stale', provisional: reason === 'provisional',
    ...(reason === 'uncertain' ? { map_alignment: { mode: 'automatic' as const, state: 'uncertain' as const,
      precision_verified: false, uncertainty_px: 12, reason: 'Precision unverified' } } : {}),
  };
  rerender(<PositionPanel {...props} image={reason === 'mismatched picture' ? { ...props.image, sourceId: 'other' } : props.image}
    snapshot={{ ...props.snapshot, position }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm map' }));
  expect(screen.queryByRole('heading', { name: 'Map confirmed' })).toBeNull();
  expect(command).not.toHaveBeenCalled();
  expect(props.snapshot.readiness.combat.ready).toBe(false);
});

it('waits for verified automatic alignment and readable map identity before confirmation', () => {
  const automatic = { ...tracked, map_alignment: { mode: 'automatic' as const, state: 'ready' as const,
    precision_verified: true, uncertainty_px: 2, reason: 'Validated' } };
  const { props, rerender, command } = setup(automatic);
  rerender(<PositionPanel {...props} snapshot={{ ...props.snapshot, catalog: { active_map: 'Floor', map_filter_held: true } }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm map' }));
  expect(screen.getByRole('status').textContent).toContain('Waiting for a readable map name');
  expect(sessionStorage.getItem('maple-map-confirmation')).toBeNull();
  rerender(<PositionPanel {...props} snapshot={{ ...props.snapshot, catalog: { active_map: 'Floor' } }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm map' }));
  expect(screen.getByRole('heading', { name: 'Map confirmed' })).toBeTruthy();
  rerender(<PositionPanel {...props} snapshot={{ ...props.snapshot, catalog: { active_map: 'Floor' },
    position: { ...automatic, kind: 'unknown', stale: true, marker: null } }} />);
  expect(screen.getByRole('heading', { name: 'Map confirmed' })).toBeTruthy();
  expect(screen.getByRole('status').textContent).toContain('Waiting for a fresh position');
  expect(command).not.toHaveBeenCalled();
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
