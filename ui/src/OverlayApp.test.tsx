import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { OverlayApp } from './OverlayApp';
import { OverlayClient } from './overlay';
import type { OverlayEvent } from './overlay';
import { json, snapshot } from './test-fixtures';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); delete window.mapleOverlay; });

it('draws the early detection packet and never falls back to old boxes after invalidation', async () => {
  let listener: (event: OverlayEvent) => void = () => {};
  const old = snapshot();
  let current = snapshot({ live_detections: { frame: old.frame,
    player: { ...old.player!, box: { x: 123, y: 234, width: 40, height: 50 } } } });
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(current);
    const command = JSON.parse(String(options?.body));
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => { listener = callback; return () => {}; } };
  const client = new OverlayClient('token', fetcher);
  render(<OverlayApp client={client} />);
  await waitFor(() => expect(client.getState().connected).toBe(true));
  act(() => listener({ type: 'game-bounds', value: { x: 0, y: 0, width: 1024, height: 768, visible: true } }));
  await waitFor(() => expect(screen.getByLabelText('Live detections').querySelector('rect')?.getAttribute('x')).toBe('123'));
  current = snapshot({ live_detections: null });
  await act(async () => { await client.readStatus(); });
  expect(screen.queryByLabelText('Live detections')).toBeNull();
  current = snapshot({ live_detections: { frame: { ...old.frame, captured_at: Date.now() / 1000 - 2 }, player: old.player } });
  await act(async () => { await client.readStatus(); });
  expect(screen.queryByLabelText('Live detections')).toBeNull();
});

it('opens Off, loads map choices without colliding, and selects an activity without input', async () => {
  const commands: string[] = [];
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot({ capture_only: false }));
    const command = JSON.parse(String(options?.body));
    commands.push(command.name);
    return json(command.name === 'area_list' ? { areas: [{ id: 'map1', name: 'Saved map', revision: 1 }] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(), subscribe: () => () => {} };
  render(<OverlayApp client={new OverlayClient('token', fetcher)} />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'Saved map' })).toBeTruthy());
  expect(screen.getByText('BOT OFF')).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
  fireEvent.change(screen.getByRole('combobox', { name: 'Activity' }), { target: { value: 'arm' } });
  expect(commands).toEqual(['area_list']);
  fireEvent.click(screen.getByRole('button', { name: 'Close · F7' }));
  expect(window.mapleOverlay.settings).toHaveBeenCalledWith(false);
  expect(commands).toEqual(['area_list']);
});

it('handles F6 with settings open and shows an immediate engine stop reason', async () => {
  const commands: string[] = [];
  let listener: (event: OverlayEvent) => void = () => {};
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot({ focused: false,
      reason: 'No confident same-platform targets; stopped' }));
    const command = JSON.parse(String(options?.body)); commands.push(command.name);
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  window.mapleOverlay = { settings: vi.fn(async open => listener({ type: 'panel', value: open })),
    quit: vi.fn(), heartbeat: vi.fn(), subscribe: callback => { listener = callback; return () => {}; } };
  render(<OverlayApp client={new OverlayClient('token', fetcher)} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Turn On · F6' }).hasAttribute('disabled')).toBe(false));
  act(() => listener({ type: 'toggle' }));
  await waitFor(() => expect(commands).toContain('dry_run'));
  expect(window.mapleOverlay.settings).toHaveBeenCalledWith(false);
  await waitFor(() => expect(screen.getByText('Decision preview stopped: No confident same-platform targets; stopped')).toBeTruthy());
  // A second On while another app has focus is explained, never dispatched.
  act(() => listener({ type: 'toggle' }));
  await waitFor(() => expect(screen.getByText('F6 · focus the game to turn On; F8 always stops')).toBeTruthy());
  expect(commands.filter(name => name === 'dry_run')).toHaveLength(1);
});
