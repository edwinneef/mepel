import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { OverlayApp } from './OverlayApp';
import { OverlayClient } from './overlay';
import { DashboardSession } from './dashboard';
import { deferred, json, snapshot } from './test-fixtures';
import type { AreaProfile } from './contracts';

beforeEach(() => {
  vi.stubGlobal('Image', class { src = ''; decode = async () => {}; });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function setup() {
  let current = snapshot();
  current = { ...current, frame: { ...current.frame, source_id: `${current.session_id}:source:1` },
    attack_setup: { minimum_px: 10, maximum_px: 90, measured: false, reason: '' } };
  const requests: { url: string; body: Record<string, unknown> }[] = [];
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (url === '/api/v1/status') return json(current);
    if (url === '/api/v1/drawings') return json(null);
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    const body = JSON.parse(String(options?.body));
    requests.push({ url: String(url), body });
    return json(body.name === 'area_list' ? { areas: [] } : { connected: true, panel: body.panel });
  });
  vi.stubGlobal('fetch', fetcher);
  const client = new OverlayClient('token', fetcher);
  const dashboard = new DashboardSession('token', fetcher);
  return { client, dashboard, requests, fetcher, current };
}

it('opens on Run with four pages and closes its lease gate before requesting a countdown', async () => {
  const { client, dashboard, requests } = setup();
  render(<OverlayApp client={client} dashboard={dashboard} />);
  await waitFor(() => expect(client.getState().busy).toBe(false));
  await waitFor(() => expect(client.getState().connected).toBe(true));
  for (const name of ['Run', 'Set up', 'Maps', 'History']) expect(screen.getByRole('button', { name })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Run' }).getAttribute('aria-current')).toBe('page');
  expect(screen.getByRole('radio', { name: /Watch only/ }).getAttribute('aria-checked')).toBe('true');
  // Set up holds the settings flag (bot off); Start closes it again before the countdown.
  fireEvent.click(screen.getByRole('button', { name: 'Set up' }));
  await waitFor(() => expect(requests.some(r => r.url === '/api/dashboard' && r.body.panel === true)).toBe(true));
  fireEvent.click(screen.getByRole('button', { name: 'Run' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Start' }).hasAttribute('disabled')).toBe(false));
  const opened = requests.length;
  fireEvent.click(screen.getByRole('button', { name: 'Set up' }));
  await waitFor(() => expect(requests.slice(opened).some(r => r.url === '/api/dashboard' && r.body.panel === true)).toBe(true));
  fireEvent.keyDown(window, { key: 'F6' });
  await waitFor(() => expect(requests.some(r => r.body.name === 'dry_run')).toBe(true));
  const start = requests.findIndex(r => r.body.name === 'dry_run');
  expect(requests.slice(opened, start).some(r => r.url === '/api/dashboard' && r.body.panel === false)).toBe(true);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Run' }).getAttribute('aria-current')).toBe('page'));
  expect(requests.filter(r => r.body.name === 'dry_run')).toHaveLength(1);
  fireEvent.keyDown(window, { key: 'F8' });
  await waitFor(() => expect(requests.some(r => r.body.name === 'stop')).toBe(true));
  fireEvent(window, new Event('pagehide'));
  expect(requests.some(r => r.url === '/api/dashboard_disconnect')).toBe(true);
  expect(dashboard.disconnected).toBe(true);
});

it('keeps every control of the old tabs reachable on the four pages', async () => {
  const { client, dashboard } = setup();
  render(<OverlayApp client={client} dashboard={dashboard} />);
  await waitFor(() => expect(client.getState().connected && !client.getState().busy).toBe(true));
  // Run: record, other activities, layers, Stop.
  for (const name of ['Record 30 s', 'Potions only', 'Combat without a loop', 'Enemies', 'Attack range', 'Map lines']) {
    expect(screen.getByRole('button', { name })).toBeTruthy();
  }
  expect(screen.getAllByRole('button', { name: /Stop/ }).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: 'Set up' }));
  expect(screen.getByRole('button', { name: 'Player and enemy setup' })).toBeTruthy(); // Bowman setup (old Bot tab)
  for (const [section, text] of [['Connection', 'Calibration picture and selection'], ['Recognition', 'Recognition'], ['Potions', 'Potions']]) {
    fireEvent.click(screen.getByRole('button', { name: section }));
    expect(screen.getAllByText(text).length).toBeGreaterThan(0);
  }
  fireEvent.click(screen.getByRole('button', { name: 'Maps' }));
  expect(screen.getByLabelText('Map for path builder')).toBeTruthy();
  expect(screen.getByText('Map tracking')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'History' }));
  expect(screen.getByText('Diagnostics')).toBeTruthy();
  expect(screen.getByText('Combat and potion evidence')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Disconnect dashboard' })).toBeTruthy();
});

it('runs an activity picked under Other activities and returns to the plans', async () => {
  const { client, dashboard, requests, current } = setup();
  render(<OverlayApp client={client} dashboard={dashboard} />);
  await waitFor(() => expect(client.getState().connected && !client.getState().busy).toBe(true));
  fireEvent.click(screen.getByText('Other activities'));
  expect(screen.getByRole('button', { name: 'Potions only' }).hasAttribute('disabled')).toBe(true); // capture-only session
  current.capture_only = false;
  await act(async () => { await client.readStatus(); });
  fireEvent.click(screen.getByRole('button', { name: 'Potions only' }));
  expect(screen.getByText('Selected in Set up')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Back to the plans' }));
  expect(screen.getByText('What should it do?')).toBeTruthy();
  expect(requests.some(r => r.body.name === 'autopotter_live')).toBe(false);
});

it('Stop cancels a start while the browser waits for settings closure acknowledgement', async () => {
  const { client, dashboard, requests } = setup();
  const close = deferred<void>();
  render(<OverlayApp client={client} dashboard={dashboard} />);
  await waitFor(() => expect(client.getState().connected && !client.getState().busy).toBe(true));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Start' }).hasAttribute('disabled')).toBe(false));
  vi.spyOn(dashboard, 'settings').mockReturnValue(close.promise);
  fireEvent.click(screen.getByRole('button', { name: 'Start' }));
  fireEvent.keyDown(window, { key: 'F8' });
  await act(async () => close.resolve());
  expect(requests.some(r => r.body.name === 'dry_run')).toBe(false);
  expect(requests.some(r => r.body.name === 'stop')).toBe(true);
});

it('does not renew or retry a rejected lease and preserves the refusal message', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ error: 'Another overlay is connected' }, 400));
  const dashboard = new DashboardSession('token', fetcher);
  await expect(dashboard.settings(false)).rejects.toThrow('Another overlay is connected');
  dashboard.heartbeat();
  await expect(dashboard.settings(false)).rejects.toThrow('Reload to reconnect');
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it('never renews a stale open-panel state after a queued close', async () => {
  const first = deferred<Response>();
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ connected: true }));
  fetcher.mockReturnValueOnce(first.promise);
  const dashboard = new DashboardSession('token', fetcher);
  const opening = dashboard.settings(true);
  await Promise.resolve();
  const closing = dashboard.settings(false);
  dashboard.heartbeat();
  first.resolve(json({ connected: true }));
  await opening; await closing;
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  expect(fetcher.mock.calls.map(call => JSON.parse(String(call[1]?.body)).panel)).toEqual([true, false, false]);
});

it('explains a refused control connection while the game picture stays connected and never retries it', async () => {
  const { client, dashboard, fetcher } = setup();
  const original = fetcher.getMockImplementation()!;
  fetcher.mockImplementation((url, options) => url === '/api/dashboard'
    ? Promise.resolve(json({ error: 'Another overlay is connected' }, 409)) : original(url, options));
  render(<OverlayApp client={client} dashboard={dashboard} />);
  const banner = await screen.findByRole('alert', { name: 'Dashboard controls disconnected' });
  expect(banner.textContent).toContain('Another overlay is connected');
  expect(banner.textContent).toContain('Connecting the MapleStory window supplies the picture');
  expect(client.getState().connected).toBe(true);
  const denied = fetcher.mock.calls.filter(call => call[0] === '/api/dashboard').length;
  dashboard.heartbeat();
  await Promise.resolve();
  expect(fetcher.mock.calls.filter(call => call[0] === '/api/dashboard')).toHaveLength(denied);
  expect(screen.getByRole('button', { name: 'Start' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Maps' }));
  await waitFor(() => expect(client.getState().busy).toBe(false));
  // Saved maps load by themselves; the map picker stays usable without dashboard control.
  await waitFor(() => expect(screen.getByLabelText('Map for path builder').hasAttribute('disabled')).toBe(false));
});

it('disconnects the lease if status polling loses the engine and never resumes automatically', async () => {
  const { client, dashboard, fetcher, requests } = setup();
  render(<OverlayApp client={client} dashboard={dashboard} />);
  await waitFor(() => expect(client.getState().connected).toBe(true));
  fetcher.mockRejectedValue(new Error('Network lost'));
  await waitFor(() => expect(dashboard.disconnected).toBe(true));
  expect(fetcher.mock.calls.some(call => call[0] === '/api/dashboard_disconnect')).toBe(true);
  expect(requests.some(r => r.body.name === 'arm')).toBe(false);
});

it('scales all layers with the displayed frame and hides them on source mismatch', async () => {
  const { client, dashboard, fetcher, current } = setup();
  const map: AreaProfile = { schema_version: 2, id: 'map', revision: 3, name: 'Map',
    boundary: { x: 0, y: 0, width: 1024, height: 768 }, views: [], zones: [], links: [], ropes: [],
    platforms: [{ id: 'floor', start: { x: 100, y: 200 }, end: { x: 300, y: 200 } }] };
  const position = { area_id: 'map', kind: 'platform' as const, surface_id: 'floor', input_sent: false as const,
    reason: 'Matched', captured_at: current.frame.captured_at!, projection: { x: 0, y: 0, scale: 1, revision: 3 } };
  let source = current.frame.source_id;
  fetcher.mockImplementation(async (url, options) => {
    if (url === '/api/v1/status') return json({ ...current, position });
    if (url === '/api/v1/drawings') return json({ frame: { ...current.frame, source_id: source }, player: current.player, position,
      terrain: { ...position, alignment: { valid: true } } });
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    const body = JSON.parse(String(options?.body));
    return json(body.name === 'area_list' ? { areas: [] } : body.name === 'area_load' ? { profile: map } : { connected: true });
  });
  render(<OverlayApp client={client} dashboard={dashboard} />);
  await waitFor(() => expect(screen.getByLabelText('Detection boxes')).toBeTruthy());
  const layer = screen.getByLabelText('Detection boxes').closest('svg')!;
  expect(layer.getAttribute('viewBox')).toBe('0 0 1024 768');
  expect(layer.parentElement?.querySelector('img')?.width).toBe(1024);
  expect(screen.getByLabelText('Configured attack range').closest('svg')).toBe(layer);
  await waitFor(() => expect(screen.getByLabelText('Platform names').closest('svg')).toBe(layer));
  fireEvent.click(screen.getByRole('button', { name: '200%' }));
  expect(layer.getAttribute('viewBox')).toBe('0 0 1024 768');
  expect(layer.closest('.game-scroll')?.firstElementChild?.getAttribute('style')).toContain('2048px');
  source = `${current.session_id}:source:other`;
  await waitFor(() => expect(screen.queryByLabelText('Detection boxes')).toBeNull());
});

it('starts One platform through the in-game overlay and explains a refusal', async () => {
  const { client, dashboard, requests, current, fetcher } = setup();
  Object.assign(current, { capture_only: false, focused: true,
    position: { area_id: 'a'.repeat(32), area_name: 'Snail Hunting Ground III', kind: 'platform', surface_id: 'fh66', reason: '', input_sent: false },
    readiness: { preview: { ready: true, reason: '' }, combat: { ready: true, reason: 'Ready' }, potions: { ready: true, reason: '' } },
    probes: Object.fromEntries(['left', 'right', 'attack', 'jump', 'skill'].map(name => [name, { confirmed: true }])) });
  const original = fetcher.getMockImplementation()!;
  let refuse = true;
  fetcher.mockImplementation(async (url, options) => {
    if (url === '/api/dashboard_batch') {
      requests.push({ url: String(url), body: JSON.parse(String(options?.body)) });
      return refuse ? json({ error: 'Start the in-game overlay first; batches run through it' }, 400) : json({ queued: true, id: 1 });
    }
    return original(url, options);
  });
  render(<OverlayApp client={client} dashboard={dashboard} />);
  await waitFor(() => expect(client.getState().connected && !client.getState().busy).toBe(true));
  fireEvent.click(screen.getByRole('radio', { name: /Stay on this platform/ }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Start' }).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Start' }));
  await waitFor(() => expect(screen.getAllByText(/Start the in-game overlay first/).length).toBeGreaterThan(0));
  refuse = false;
  fireEvent.click(screen.getByRole('button', { name: 'Start' }));
  await waitFor(() => expect(screen.getByText('Waiting for the in-game overlay to start it')).toBeTruthy());
  const queued = requests.filter(r => r.url === '/api/dashboard_batch').map(r => r.body);
  expect(queued.at(-1)).toMatchObject({ kind: 'single', area: 'a'.repeat(32), minutes: 15 });
  expect(typeof queued.at(-1)!.owner).toBe('string');
  // Nothing goes to the engine's own start commands for a batch plan.
  expect(requests.some(r => ['arm', 'dry_run'].includes(String(r.body.name)))).toBe(false);
});

it('sends its drawing toggles with each heartbeat', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ connected: true }));
  const dashboard = new DashboardSession('token', fetcher);
  dashboard.setDisplay({ enemies: false, range: true, lines: true });
  await dashboard.settings(false);
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body)).display).toEqual({ enemies: false, range: true, lines: true });
});
