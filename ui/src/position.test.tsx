import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EngineClient } from './client';
import type { LivePosition, TaughtGeometry } from './contracts';
import { PositionOverlay, PositionPanel } from './PositionPanel';
import { snapshot } from './test-fixtures';

afterEach(() => cleanup());

const geometry: TaughtGeometry = {
  platforms: [{ id: 'walk_p1', name: 'Ground floor', start: { x: 30, y: 593 }, end: { x: 1308, y: 593 } },
    { id: 'walk_p2', name: 'Left ledge', start: { x: 400, y: 445 }, end: { x: 700, y: 445 } }],
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
  const props = { snapshot: snapshot({ position }), client, act: async (operation: () => Promise<unknown>) => { await operation(); },
    disabled: false, areas: [{ id: 'a'.repeat(32), name: 'Floor', revision: 2 }], refreshAreas };
  return { command, refreshAreas, props, ...render(<PositionPanel {...props} />) };
}

it('tracks a saved map or creates a new map without starting gameplay', async () => {
  const { command, refreshAreas } = setup(null);
  fireEvent.change(screen.getByLabelText('Saved map'), { target: { value: 'a'.repeat(32) } });
  fireEvent.click(screen.getByRole('button', { name: 'Track selected map' }));
  expect(command).toHaveBeenCalledWith('position_start', { area_id: 'a'.repeat(32) });
  fireEvent.click(screen.getByText('Other map actions'));
  fireEvent.change(screen.getByLabelText('Map name'), { target: { value: 'Ant Tunnel' } });
  fireEvent.click(screen.getByRole('button', { name: 'Teach a new map' }));
  await waitFor(() => expect(refreshAreas).toHaveBeenCalled());
  expect(command).toHaveBeenCalledWith('teach_new_area', { name: 'Ant Tunnel' });
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

it('keeps finishing a draft separate from using the map', async () => {
  const { command } = setup(tracked);
  fireEvent.click(screen.getByRole('button', { name: 'Teach this map' }));
  expect(command).toHaveBeenCalledWith('teach_begin', {});
  cleanup();
  const recording = setup({ ...tracked, teaching: { phase: 'recording', geometry, samples: 120 } });
  expect(screen.getByText(/2 platforms learned/)).toBeTruthy();
  const finish = screen.getByRole('button', { name: 'Finish teaching' });
  expect(finish.compareDocumentPosition(screen.getAllByRole('img', { name: 'Learned map' })[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(finish);
  expect(recording.command).toHaveBeenCalledWith('teach_finish', {});
  cleanup();
  const review = setup({ ...tracked, teaching: { phase: 'review', geometry, samples: 120, map_revision: 2 } });
  expect(screen.getByText(/stays unchanged until you choose Use this map/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Use this map' }));
  await waitFor(() => expect(review.command).toHaveBeenCalledWith('teach_save', {}));
});

it('shows calibration progress and offers a safe pause', () => {
  const { command } = setup({ ...tracked, calibration: { active: true, pairs: 7, rejected: 0, saved: null },
    teaching: { phase: 'calibrating', geometry: null, samples: 0 } });
  expect(screen.getByText(/7 of 20 samples/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Pause teaching' }));
  expect(command).toHaveBeenCalledWith('teach_pause', {});
});

it('does not resume a recovered draft until explicitly requested', () => {
  const { command } = setup({ ...tracked, teaching: { phase: 'interrupted', geometry, samples: 120,
    draft: { id: 'draft', revision: 4, saved_at: 1, saved: true, error: null } } });
  expect(command).not.toHaveBeenCalled();
  expect(screen.getByText(/Draft checkpoint saved/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Resume teaching' }));
  expect(command).toHaveBeenCalledWith('teach_resume', {});
});

it('explains recorded route gaps without claiming a move is impossible', () => {
  const broken = { ...geometry, problems: { home: 'walk_p1', unreachable: [], stranded: ['walk_p2'] } };
  const { command, container } = setup({ ...tracked, teaching: { phase: 'review', geometry: broken, samples: 0 } });
  expect(container.querySelector('.route-explanation')?.textContent).toContain('No return journey was recorded from Left ledge to Ground floor');
  expect(screen.queryByText(/Jump or drop back down/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Continue teaching' }));
  expect(command).toHaveBeenCalledWith('teach_resume', {});
});

it('prepares a report from a failed recording instead of asking for another walk', async () => {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
  const broken = { ...geometry, problems: { home: 'walk_p1', unreachable: [], stranded: ['walk_p2'] } };
  const { command } = setup({ ...tracked, teaching: { phase: 'review', geometry: broken, samples: 0,
    health: { checks: 913, misses: 373, last_reason: 'Minimap unreadable' } } });
  fireEvent.click(screen.getByRole('button', { name: 'Copy tracking report' }));
  const report = await screen.findByRole('textbox', { name: /Tracking report/ });
  expect((report as HTMLTextAreaElement).value).toContain('373');
  expect(command).not.toHaveBeenCalled();
});

it('requires a separate confirmation before replacing a smaller or incomplete map', async () => {
  const { command } = setup({ ...tracked, teaching: { phase: 'review', geometry, samples: 120 } });
  command.mockResolvedValueOnce({ requires_confirmation: true, platforms_before: 12, platforms_after: 3, zones_removed: 1 });
  fireEvent.click(screen.getByRole('button', { name: 'Use this map' }));
  const confirm = await screen.findByRole('alertdialog', { name: 'Confirm map replacement' });
  expect(confirm.textContent).toContain('12 saved platforms → 3 learned platforms');
  expect(command).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Replace with this draft' }));
  await waitFor(() => expect(command).toHaveBeenLastCalledWith('teach_save', { confirm_partial: true }));
});

it('offers retry after a failed checkpoint and preserves the draft', () => {
  const { command } = setup({ ...tracked, teaching: { phase: 'review', geometry, samples: 20,
    draft: { id: 'draft', revision: 1, saved_at: 1, saved: false, error: 'Disk unavailable' } } });
  expect(screen.getByText('Disk unavailable')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Retry saving draft' }));
  expect(command).toHaveBeenCalledWith('teach_checkpoint', {});
});

it('shows activation failure beside the action and keeps the review', async () => {
  const { command } = setup({ ...tracked, teaching: { phase: 'review', geometry, samples: 20 } });
  command.mockRejectedValueOnce(new Error('Saved map changed elsewhere'));
  fireEvent.click(screen.getByRole('button', { name: 'Use this map' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Your teaching draft is kept');
  expect(screen.getByLabelText('Place')).toBeTruthy();
});

it('keeps selection when a merged surface aliases the old identity', () => {
  const broken = { ...geometry, problems: { home: 'walk_p1', unreachable: [], stranded: ['walk_p2'] } };
  const { rerender, props } = setup({ ...tracked, teaching: { phase: 'review', geometry: broken, samples: 20 } });
  fireEvent.change(screen.getByLabelText('Place'), { target: { value: 'walk_p2' } });
  const changed = { ...broken, platforms: [geometry.platforms[0], { ...geometry.platforms[1], id: 'walk_p3' }],
    aliases: { walk_p2: 'walk_p3' }, problems: { ...broken.problems, stranded: ['walk_p3'] } };
  rerender(<PositionPanel {...props} snapshot={snapshot({ position: { ...tracked,
    teaching: { phase: 'review', geometry: changed, samples: 20 } } })} />);
  expect((screen.getByLabelText('Place') as HTMLSelectElement).value).toBe('walk_p3');
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

it('zooms and expands saved terrain without changing annotations, teaching or map data', () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')); };
  const original = JSON.stringify(geometry);
  const { command, container } = setup({ ...tracked, teaching: { phase: 'review', geometry, samples: 120,
    references: [{ id: 'view', name: 'Floor', width: 1366, height: 768, origin: { x: 0, y: 0 }, scale: 1, image: 'saved' }] } });
  const savedPicture = container.querySelector('.terrain-image')!;
  const viewBox = savedPicture.getAttribute('viewBox');
  const outline = savedPicture.querySelector('line')?.outerHTML;
  fireEvent.click(screen.getByRole('button', { name: '100%' }));
  expect(container.querySelector('.terrain-native')?.getAttribute('style')).toContain('width: 1366px');
  fireEvent.click(screen.getByRole('button', { name: 'Expand terrain' }));
  const dialog = screen.getByRole('dialog', { name: 'Expanded terrain' });
  expect(dialog.querySelector('svg')?.getAttribute('viewBox')).toBe(viewBox);
  expect(dialog.querySelector('line')?.outerHTML).toBe(outline);
  expect(dialog.querySelector('image')?.getAttribute('href')).toBe('/api/v1/area-frame?id=saved');
  fireEvent.click(screen.getByRole('button', { name: 'Fit' }));
  expect(dialog.querySelector('.terrain-native')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Close expanded terrain' }));
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.getByRole('button', { name: 'Fit' }).getAttribute('aria-pressed')).toBe('true');
  expect(JSON.stringify(geometry)).toBe(original);
  expect(command).not.toHaveBeenCalled();
});
