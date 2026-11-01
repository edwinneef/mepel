import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { GoBar } from './GoBar';
import type { EngineClient } from './client';
import type { NavigationStatus } from './contracts';
import { snapshot } from './test-fixtures';

afterEach(cleanup);
const map: NavigationStatus['map'] = { area_id: 'area', revision: 4, home: 'p3', usable_edges: 2, disabled_edges: {}, nodes: [
  { id: 'p3', name: 'Ground floor · P3', kind: 'platform', excluded: false },
  { id: 'p2', name: 'Middle ledge · P2', kind: 'platform', excluded: false },
  { id: 'p16', name: 'Ground floor 2 · P16', kind: 'platform', excluded: true }] };
const navigation: NavigationStatus = { stage: 'idle', reason: 'Choose', active: false, ready: false, blocker: null, route: null, map };

function setup(changes: Parameters<typeof snapshot>[0], command = vi.fn().mockResolvedValue({ areas: [{ id: 'area', name: 'Over the Wall' }] })) {
  render(<GoBar snapshot={snapshot({ capture_only: false, ...changes })} client={{ command } as unknown as EngineClient}
    disabled={false} act={async operation => { try { await operation(); } catch { /* shown inline */ } }} />);
  return command;
}

it('tracks the chosen map before listing destinations, sending no movement', async () => {
  const command = setup({ navigation: { ...navigation, map: null } });
  await waitFor(() => expect(screen.getByRole('option', { name: 'Over the Wall' })).toBeTruthy());
  fireEvent.change(screen.getByRole('combobox', { name: 'Map to track' }), { target: { value: 'area' } });
  fireEvent.click(screen.getByRole('button', { name: 'Track map' }));
  await waitFor(() => expect(command).toHaveBeenCalledWith('position_start', { area_id: 'area' }));
  expect(command.mock.calls.map(([name]) => name)).not.toContain('nav_go');
});

it('tracks the map detected from the minimap when none is chosen', async () => {
  const command = setup({ navigation: { ...navigation, map: null } });
  fireEvent.click(screen.getByRole('button', { name: 'Track map' }));
  await waitFor(() => expect(command).toHaveBeenCalledWith('position_start', {}));
});

it('goes from the current platform in one click and shows a refusal inline', async () => {
  const command = vi.fn().mockRejectedValue(new Error('Waiting for fresh fused position on the previewed origin'));
  setup({ navigation, position: { area_id: 'area', kind: 'platform', surface_id: 'p3', reason: 'On P3', input_sent: false } }, command);
  const destination = screen.getByRole('combobox', { name: 'Go destination' });
  expect(destination.querySelector('option[value="p3"]')).toBeNull();
  expect(destination.querySelector('option[value="p16"]')).toBeNull();
  expect(screen.getByText('You are on Ground floor · P3')).toBeTruthy();
  fireEvent.change(destination, { target: { value: 'p2' } });
  fireEvent.click(screen.getByRole('button', { name: "Go (I'm supervising)" }));
  await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/fresh fused position/));
  expect(command).toHaveBeenCalledExactlyOnceWith('nav_go', { target: 'p2', opt_in: true });
  expect((screen.getByRole('button', { name: "Go (I'm supervising)" }) as HTMLButtonElement).disabled).toBe(false);
});
