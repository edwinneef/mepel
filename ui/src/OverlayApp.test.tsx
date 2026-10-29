import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { OverlayApp } from './OverlayApp';
import { OverlayClient } from './overlay';
import type { OverlayEvent } from './overlay';
import type { LiveDetections } from './contracts';
import { json, snapshot } from './test-fixtures';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); delete window.mapleOverlay; });

it('keeps settings closed until the native overlay explicitly opens them', async () => {
  let listener: (event: OverlayEvent) => void = () => {};
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (url === '/api/v1/status') return json(snapshot());
    const command = JSON.parse(String(options?.body));
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => { listener = callback; return () => {}; } };
  const client = new OverlayClient('token', fetcher);
  render(<OverlayApp client={client} />);
  await waitFor(() => expect(client.getState().connected).toBe(true));
  expect(screen.queryByLabelText('Overlay settings')).toBeNull();
  expect(screen.getByText('BOT OFF')).toBeTruthy();
  act(() => listener({ type: 'panel', value: true }));
  expect(screen.getByLabelText('Overlay settings')).toBeTruthy();
  expect(window.mapleOverlay.settings).not.toHaveBeenCalled();
});

it('uses the fast drawing stream without replacing authoritative observations or reviving them on loss', async () => {
  let listener: (event: OverlayEvent) => void = () => {};
  const authoritative = snapshot();
  let drawing: LiveDetections | null = { display: true,
    frame: { ...authoritative.frame, source_id: `${authoritative.session_id}:source:1`, id: 'display:1' },
    player: { ...authoritative.player!, track_id: 'player:1', box: { x: 100, y: 200, width: 40, height: 50 } } };
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (url === '/api/v1/drawings') return json(drawing);
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(authoritative);
    const command = JSON.parse(String(options?.body));
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => { listener = callback; callback({ type: 'panel', value: true }); return () => {}; } };
  const client = new OverlayClient('token', fetcher);
  render(<OverlayApp client={client} />);
  await waitFor(() => expect(client.getState().connected).toBe(true));
  act(() => listener({ type: 'game-bounds', value: { x: 0, y: 0, width: 1024, height: 768, visible: true } }));
  await waitFor(() => expect(screen.getByLabelText('Detection boxes').querySelector('rect')?.getAttribute('x')).toBe('100'));
  expect(client.getState().snapshot?.player?.box.x).toBe(450);
  expect(screen.getByRole('button', { name: 'Turn On · F6' })).toBeTruthy();
  drawing = null;
  await waitFor(() => expect(screen.queryByLabelText('Detection boxes')).toBeNull());
  expect(client.getState().snapshot?.player?.box.x).toBe(450);
});

it('draws the early detection packet and never falls back to old boxes after invalidation', async () => {
  let listener: (event: OverlayEvent) => void = () => {};
  const old = snapshot();
  let current = snapshot({ attack_setup: { minimum_px: 0, maximum_px: 90, measured: false, reason: '' }, live_detections: { frame: old.frame,
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
    subscribe: callback => { listener = callback; callback({ type: 'panel', value: true }); return () => {}; } };
  const client = new OverlayClient('token', fetcher);
  render(<OverlayApp client={client} />);
  await waitFor(() => expect(client.getState().connected).toBe(true));
  act(() => listener({ type: 'game-bounds', value: { x: 0, y: 0, width: 1024, height: 768, visible: true } }));
  await waitFor(() => expect(screen.getByLabelText('Live detections').querySelector('rect')?.getAttribute('x')).toBe('123'));
  expect(screen.getByLabelText('Configured attack range')).toBeTruthy();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Show attack range' }));
  expect(screen.queryByLabelText('Configured attack range')).toBeNull();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Show attack range' }));
  expect(screen.getByLabelText('Configured attack range')).toBeTruthy();
  current = snapshot({ live_detections: null });
  await act(async () => { await client.readStatus(); });
  expect(screen.queryByLabelText('Live detections')).toBeNull();
  expect(screen.queryByLabelText('Configured attack range')).toBeNull();
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
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => { callback({ type: 'panel', value: true }); return () => {}; } };
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
    quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => { listener = callback; callback({ type: 'panel', value: true }); return () => {}; } };
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

it('selects Bowman probes directly without input and preserves confirmation identity', async () => {
  const commands: { name: string; payload: Record<string, unknown> }[] = [];
  let current = snapshot({ capture_only: false, bindings: { attack: 'space', skill: 'ctrl' },
    attack_setup: { minimum_px: 0, maximum_px: 90, measured: false, reason: 'Unmeasured' },
    probes: { left: { confirmed: true }, hp_potion: { confirmed: true } } });
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(current);
    const command = JSON.parse(String(options?.body)); commands.push(command);
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => { callback({ type: 'panel', value: true }); return () => {}; } };
  const client = new OverlayClient('token', fetcher);
  render(<OverlayApp client={client} />);
  await screen.findByRole('button', { name: 'attack' });
  expect(screen.getByText('Engine-loaded range: 0–90 px')).toBeTruthy();
  expect(screen.getByText('Hit range not yet verified')).toBeTruthy();
  expect(screen.getByText('Movement and potion controls · 2 verified')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'attack' }));
  expect(screen.getByRole('option', { name: 'Test attack' })).toBeTruthy();
  expect(commands.some(c => c.name === 'probe')).toBe(false);
  current = { ...current, active_probe: { id: 7, generation: 3, action: 'attack', phase: 'countdown', instruction: 'Focus the game' } };
  await act(async () => { await client.readStatus(); });
  expect(screen.queryByRole('button', { name: 'Confirm observed effect' })).toBeNull();
  current = { ...current, active_probe: { ...current.active_probe!, phase: 'awaiting_confirmation' } };
  await act(async () => { await client.readStatus(); });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm observed effect' }));
  await waitFor(() => expect(commands).toContainEqual(expect.objectContaining({ name: 'confirm_probe', payload: { id: 7, generation: 3 } })));
  expect(screen.getByText('Movement and potion controls · 2 verified')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Reject probe' }));
  await waitFor(() => expect(commands).toContainEqual(expect.objectContaining({ name: 'reject_probe', payload: { id: 7, generation: 3 } })));
});
