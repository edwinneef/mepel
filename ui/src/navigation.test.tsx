import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { NavigationPanel } from './NavigationPanel';
import type { EngineClient } from './client';
import type { NavigationStatus } from './contracts';
import { snapshot } from './test-fixtures';

afterEach(cleanup);
const navigation: NavigationStatus = {
  stage: 'preview', reason: 'Route preview only', active: false, ready: false,
  blocker: 'Capture-only session: navigation input locked',
  map: { area_id: 'area', revision: 4, home: 'p3', usable_edges: 29, disabled_edges: {}, nodes: [
    { id: 'p3', name: 'Ground floor · P3', kind: 'platform', excluded: false },
    { id: 'p2', name: 'Middle ledge · P2', kind: 'platform', excluded: false },
    { id: 'p16', name: 'Ground floor 2 · P16', kind: 'platform', excluded: true },
    { id: 'p5', name: 'Ledge · P5', kind: 'platform', excluded: true },
  ] },
  route: { area_id: 'area', revision: 4, fingerprint: 'hash', origin: 'p3', target: 'p2',
    edges: [{ id: 'l33', source: 'p3', target: 'p2', kind: 'jump', launch: [100, 200], landing: [200, 100], evidence: 'saved' }] },
};

function setup(nav: NavigationStatus | undefined = navigation, captureOnly = true, areaId?: string) {
  const command = vi.fn().mockResolvedValue(nav);
  const onPreview = vi.fn(), onInvalidate = vi.fn();
  render(<NavigationPanel snapshot={snapshot({ navigation: nav, capture_only: captureOnly,
    ...(areaId ? { position: { area_id: areaId, kind: 'unknown', reason: 'Unknown', input_sent: false } } : {}) })}
    client={{ command } as unknown as EngineClient} disabled={false}
    act={async operation => { await operation(); }} onPreview={onPreview} onInvalidate={onInvalidate}
    supervised={false} onSupervised={vi.fn()} areas={[{ id: 'area', name: 'Over the Wall' }]} />);
  return { command, onPreview, onInvalidate };
}

it('loads routes only on request and never starts input', async () => {
  const { command } = setup({ ...navigation, map: null, route: null });
  expect(command).not.toHaveBeenCalled();
  const track = screen.getByRole('button', { name: 'Track map and load routes' });
  expect(track.hasAttribute('disabled')).toBe(true);
  fireEvent.change(screen.getByRole('combobox', { name: 'Map to track' }), { target: { value: 'area' } });
  fireEvent.click(track);
  await waitFor(() => expect(command).toHaveBeenCalledWith('nav_refresh'));
  expect(command).toHaveBeenCalledWith('position_start', { area_id: 'area' });
  expect(command.mock.calls.map(([name]) => name)).not.toContain('nav_start');
});

it('previews named routes, disables excluded destinations and makes no movement request', async () => {
  const { command, onPreview, onInvalidate } = setup();
  const destination = screen.getByRole('combobox', { name: 'Route destination' });
  expect(destination.querySelector('option[value="p16"]')?.hasAttribute('disabled')).toBe(true);
  expect(destination.querySelector('option[value="p5"]')?.hasAttribute('disabled')).toBe(true);
  fireEvent.change(destination, { target: { value: 'p2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview route' }));
  await waitFor(() => expect(onPreview).toHaveBeenCalledOnce());
  expect(command).toHaveBeenCalledExactlyOnceWith('nav_preview', { origin: 'p3', target: 'p2' });
  expect(onInvalidate).toHaveBeenCalled();
  expect(screen.getByText('Ground floor · P3 → Middle ledge · P2')).toBeTruthy();
  expect(screen.getByText(/Hypothetical origin/)).toBeTruthy();
  expect(screen.queryByRole('checkbox')).toBeNull();
  expect(screen.queryByRole('button', { name: /Start/ })).toBeNull();
  expect(screen.getByText(/Capture-only session/)).toBeTruthy();
  fireEvent.change(destination, { target: { value: 'p3' } });
  expect(screen.queryByLabelText('Recorded route preview')).toBeNull();
});

it('offers explicit supervision only in input-capable sessions and freezes route changes while moving', () => {
  setup({ ...navigation, active: true, stage: 'flight' }, false);
  fireEvent.change(screen.getByRole('combobox', { name: 'Route destination' }), { target: { value: 'p2' } });
  expect(screen.getByRole('checkbox').hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: 'Preview route' }).hasAttribute('disabled')).toBe(true);
});

it('requires reloading evidence after tracking a different map', () => {
  setup(navigation, true, 'different-area');
  expect(screen.queryByRole('combobox', { name: 'Route destination' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Load navigation routes' }).hasAttribute('disabled')).toBe(false);
});
