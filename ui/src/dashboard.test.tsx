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

it('opens the same six tabs in the browser and closes its lease gate before requesting a countdown', async () => {
  const { client, dashboard, requests } = setup();
  render(<OverlayApp client={client} dashboard={dashboard} />);
  await waitFor(() => expect(client.getState().busy).toBe(false));
  await waitFor(() => expect(client.getState().connected).toBe(true));
  expect(screen.getByRole('region', { name: 'Overlay settings' })).toBeTruthy();
  for (const name of ['Bot', 'Connection', 'Recognition', 'Potions', 'Map', 'Diagnostics']) {
    expect(screen.getByRole('button', { name })).toBeTruthy();
  }
  fireEvent.click(screen.getByRole('button', { name: 'Turn On · F6' }));
  await waitFor(() => expect(requests.some(r => r.body.name === 'dry_run')).toBe(true));
  const start = requests.findIndex(r => r.body.name === 'dry_run');
  expect(requests.slice(0, start).some(r => r.url === '/api/dashboard' && r.body.panel === false)).toBe(true);
  expect(screen.queryByLabelText('Overlay settings')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Bot' })); // The side menu reopens settings on the Bot tab.
  await waitFor(() => expect(screen.getByLabelText('Overlay settings')).toBeTruthy());
  expect(requests.filter(r => r.body.name === 'dry_run')).toHaveLength(1);
  fireEvent.keyDown(window, { key: 'F8' });
  await waitFor(() => expect(requests.some(r => r.body.name === 'stop')).toBe(true));
  fireEvent(window, new Event('pagehide'));
  expect(requests.some(r => r.url === '/api/dashboard_disconnect')).toBe(true);
  expect(dashboard.disconnected).toBe(true);
});

it('Stop cancels a start while the browser waits for settings closure acknowledgement', async () => {
  const { client, dashboard, requests } = setup();
  const close = deferred<void>();
  vi.spyOn(dashboard, 'settings').mockReturnValue(close.promise);
  render(<OverlayApp client={client} dashboard={dashboard} />);
  await waitFor(() => expect(client.getState().connected && !client.getState().busy).toBe(true));
  fireEvent.click(screen.getByRole('button', { name: 'Turn On · F6' }));
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
  expect(screen.getByRole('button', { name: 'Turn On · F6' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Map' }));
  await waitFor(() => expect(client.getState().busy).toBe(false));
  expect(screen.getByRole('button', { name: 'Load saved farming maps' }).hasAttribute('disabled')).toBe(false);
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
  await waitFor(() => expect(screen.getByLabelText('Saved terrain projected onto game').closest('svg')).toBe(layer));
  fireEvent.click(screen.getByRole('button', { name: '200%' }));
  expect(layer.getAttribute('viewBox')).toBe('0 0 1024 768');
  expect(layer.closest('.game-scroll')?.firstElementChild?.getAttribute('style')).toContain('2048px');
  source = `${current.session_id}:source:other`;
  await waitFor(() => expect(screen.queryByLabelText('Detection boxes')).toBeNull());
});
