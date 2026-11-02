import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { OverlayApp } from './OverlayApp';
import { OverlayClient } from './overlay';
import { DashboardSession } from './dashboard';
import type { OverlayEvent } from './overlay';
import type { AreaProfile, LiveDetections, LivePosition } from './contracts';
import { deferred, json, snapshot } from './test-fixtures';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); delete window.mapleOverlay; });

it('shows detection outlines and attack range without native settings or HUD', async () => {
  const current = snapshot({ monsters: [{ kind: 'monster', box: { x: 150, y: 200, width: 30, height: 30 },
    confidence: 1, template: 'enemy', tracked: false }], attack_setup: {
    minimum_px: 0, maximum_px: 55, measured: false, reason: 'Configured band',
  } });
  let frames = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (url === '/api/v1/status') return json(current);
    // A live stream: each poll is a new frame. One repeated frame expires after 500 ms,
    // which a loaded full-suite run reaches before the toggles below.
    if (url === '/api/v1/drawings') return json({ display: true,
      frame: { ...current.frame, id: `display:${++frames}`, captured_at: Date.now() / 1000,
        source_id: `${current.session_id}:source:1` }, player: current.player,
      monsters: current.monsters, target: current.target });
    const command = JSON.parse(String(options?.body));
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => {
      callback({ type: 'game-bounds', value: { x: 20, y: 40, width: 1024, height: 768, visible: true } });
      callback({ type: 'panel', value: true });
      return () => {};
    } };
  const view = render(<OverlayApp client={new OverlayClient('token', fetcher)} outlinesOnly />);
  await waitFor(() => expect(screen.getByLabelText('Detection boxes')).toBeTruthy());
  expect(screen.queryByRole('status')).toBeNull();
  expect(screen.queryByLabelText('Overlay settings')).toBeNull();
  // Outlines only in game: no controls, settings, tabs or terrain inset.
  expect(view.container.querySelectorAll('button, input, nav, .terrain-inset')).toHaveLength(0);
  expect(view.container.querySelector('[aria-label="Live detections"]')).toBeTruthy();
  expect(screen.getByLabelText('Configured attack range')).toBeTruthy();
  expect(screen.getByLabelText('Detection boxes').querySelectorAll('rect')).toHaveLength(2);
  // The in-game overlay is outlines only: no labels or tracking diagnostics.
  expect(screen.getByLabelText('Detection boxes').querySelectorAll('text')).toHaveLength(0);
  expect(screen.queryByLabelText('Enemy tracking diagnostics')).toBeNull();
});

it('shows passive position learning progress over the focused game only', async () => {
  const calibration = { active: false, pairs: 0, rejected: 0, saved: null,
    passive: { pairs: 12, rejected: 0, reason: 'Collecting pairs while you walk (12/20)' } };
  const current = snapshot({ position: { area_id: 'area', kind: 'unknown', reason: 'Walk calibration needed',
    input_sent: false, calibration } });
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
    if (url === '/api/v1/status') return json(current);
    if (url === '/api/v1/drawings') return json(null);
    return json({ areas: [] });
  });
  vi.stubGlobal('fetch', fetcher);
  let listener: (event: OverlayEvent) => void = () => {};
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => { listener = callback; return () => {}; } };
  render(<OverlayApp client={new OverlayClient('token', fetcher)} outlinesOnly />);
  act(() => listener({ type: 'game-bounds', value: { x: 0, y: 0, width: 1024, height: 768, visible: false } }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/v1/status', expect.anything()));
  expect(screen.queryByLabelText('Position learning')).toBeNull();
  act(() => listener({ type: 'game-bounds', value: { x: 0, y: 0, width: 1024, height: 768, visible: true } }));
  await waitFor(() => expect(screen.getByLabelText('Position learning').textContent)
    .toBe('Learning position · Collecting pairs while you walk (12/20)'));
});

it('keeps dashboard drawings paired with the displayed analyzed picture while newer frames load', async () => {
  vi.stubGlobal('Image', class { src = ''; decode = async () => {}; });
  let imageNumber = 0;
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => `blob:frame-${++imageNumber}`) });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  // Freeze the clock at the frame time so a slow, loaded test run cannot age the frame past 1.5 s.
  const startedAt = Date.now();
  const clock = vi.spyOn(Date, 'now').mockReturnValue(startedAt);
  const first = snapshot();
  first.frame = { ...first.frame, source_id: `${first.session_id}:source:1`,
    captured_at: startedAt / 1000 - 0.2, age_ms: 200 };
  let current = { ...first, player: { ...first.player!, box: { x: 100, y: 200, width: 40, height: 50 } },
    preview_frame: { ...first.frame, id: 'preview:1', captured_at: first.frame.captured_at! + 0.2 } };
  const nextPicture = deferred<Response>();
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (url === '/api/v1/status') return json(current);
    if (url === '/api/v1/drawings') return json({ frame: current.preview_frame,
      player: { ...first.player!, box: { x: 900, y: 200, width: 40, height: 50 } } });
    if (String(url).startsWith('/api/v1/frame')) {
      return String(url).includes('next-frame') ? nextPicture.promise : new Response(new Blob(['first']));
    }
    if (String(url).startsWith('/api/v1/preview')) return new Response(new Blob(['preview']));
    if (url === '/api/dashboard' || url === '/api/dashboard_disconnect') return json({ ok: true });
    const command = JSON.parse(String(options?.body));
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  const client = new OverlayClient('token', fetcher);
  render(<OverlayApp client={client} dashboard={new DashboardSession('token', fetcher)} />);
  await waitFor(() => expect(screen.getByLabelText('Dashboard game view').querySelector('img')).not.toBeNull());
  const box = () => screen.queryByLabelText('Detection boxes')?.querySelector('rect');
  expect(box()?.getAttribute('x')).toBe('100');
  const oldPicture = screen.getByAltText('Live game preview');
  const oldUrl = oldPicture.getAttribute('src');
  current = { ...current, frame: { ...first.frame, id: 'next-frame', sequence: 2 },
    player: { ...current.player, box: { x: 200, y: 200, width: 40, height: 50 } } };
  await act(async () => { await client.readStatus(); });
  expect(box()?.getAttribute('x')).toBe('100');
  expect(oldPicture.getAttribute('src')).toBe(oldUrl);
  await act(async () => { nextPicture.resolve(new Response(new Blob(['second']))); });
  await waitFor(() => expect(box()?.getAttribute('x')).toBe('200'));
  expect(oldPicture.getAttribute('src')).not.toBe(oldUrl);
  expect(client.getState().snapshot?.player?.box.x).toBe(200);
  expect(fetcher.mock.calls.some(([, options]) => options?.body && /"name":"(arm|nav_start|probe)"/.test(String(options.body)))).toBe(false);
  clock.mockReturnValue((first.frame.captured_at! + 2) * 1000);
  await act(async () => { await client.readStatus(); });
  expect(box()).toBeUndefined();
});

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

it('records a 30 second clip from the Bot tab and shows the countdown while it runs', async () => {
  const commands: { name: string; payload: unknown }[] = [];
  let recording = false;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot(recording ? { recorder: { full: true, full_remaining: 29.2 } } : {}));
    const command = JSON.parse(String(options?.body));
    commands.push({ name: command.name, payload: command.payload });
    if (command.name === 'record') recording = !recording;
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => { callback({ type: 'panel', value: true }); return () => {}; } };
  const client = new OverlayClient('token', fetcher);
  render(<OverlayApp client={client} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Record 30 s' }).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Record 30 s' }));
  await waitFor(() => expect(commands).toContainEqual({ name: 'record', payload: { seconds: 30 } }));
  expect(window.mapleOverlay.settings).toHaveBeenCalledWith(false);
  await act(() => client.readStatus());
  await waitFor(() => expect(screen.getByText('REC 30 s')).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Stop recording · 30 s left' }));
  await waitFor(() => expect(commands.filter(c => c.name === 'record')).toEqual([
    { name: 'record', payload: { seconds: 30 } }, { name: 'record', payload: {} }]));
});

it('opens settings from the HUD button when hotkeys are swallowed by the game', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot());
    const command = JSON.parse(String(options?.body));
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  let listener: (event: OverlayEvent) => void = () => {};
  window.mapleOverlay = { settings: vi.fn(async open => listener({ type: 'panel', value: open })),
    quit: vi.fn(), heartbeat: vi.fn(), subscribe: callback => { listener = callback; return () => {}; } };
  render(<OverlayApp client={new OverlayClient('token', fetcher)} />);
  fireEvent.click(screen.getByRole('button', { name: '⚙ Settings' }));
  expect(window.mapleOverlay.settings).toHaveBeenCalledWith(true);
  await waitFor(() => expect(screen.getByRole('region', { name: 'Overlay settings' })).toBeTruthy());
  expect(screen.queryByRole('button', { name: '⚙ Settings' })).toBeNull();
});

it('recovers platform names after a failed map load without cycling Map', async () => {
  const position: LivePosition = { area_id: 'map', kind: 'platform', surface_id: 'floor', reason: 'Matched',
    input_sent: false, captured_at: Date.now() / 1000, projection: { x: 0, y: 0, scale: 1, revision: 3 } };
  const profile: AreaProfile = { schema_version: 2, id: 'map', revision: 3, name: 'Map',
    boundary: { x: 0, y: 0, width: 1000, height: 1000 }, views: [], zones: [], links: [],
    platforms: [{ id: 'floor', name: 'Level 7', start: { x: 100, y: 200 }, end: { x: 300, y: 200 } },
      { id: 'ledge', name: 'Level 8', start: { x: 100, y: 120 }, end: { x: 300, y: 120 } }], ropes: [] };
  const current = snapshot({ position });
  let mapLoads = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    current.frame.captured_at = Date.now() / 1000;
    position.captured_at = Date.now() / 1000;
    if (url === '/api/v1/status') return json(current);
    // The live display feed sends no terrain alignment here; the position still projects.
    if (url === '/api/v1/drawings') return json({ display: true, terrain: null, position,
      frame: { ...current.frame, id: 'display:1', source_id: `${current.session_id}:source:1` },
      player: current.player, monsters: [], target: null });
    const command = JSON.parse(String(options?.body));
    if (command.name === 'area_load' && mapLoads++ === 0) throw new Error('Temporary map load failure');
    return json(command.name === 'area_load' ? { profile } : { areas: [] });
  });
  vi.stubGlobal('fetch', fetcher);
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => {
      callback({ type: 'game-bounds', value: { x: 20, y: 40, width: 1024, height: 768, visible: true } });
      return () => {};
    } };
  render(<OverlayApp client={new OverlayClient('token', fetcher)} outlinesOnly />);
  await waitFor(() => expect(screen.getByLabelText('Platform names')).toBeTruthy(), { timeout: 2500 });
  expect(screen.getByText('Level 7')).toBeTruthy();
  expect(screen.getByText('Level 8')).toBeTruthy();
});


