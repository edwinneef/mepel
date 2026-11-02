import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from './App';
import { EngineClient } from './client';
import { AlarmBanner } from './AlarmBanner';
import { json, snapshot } from './test-fixtures';

beforeEach(() => {
  vi.stubGlobal('Image', class { src = ''; decode = async () => {}; });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('requires an explicit feeding interval before farming and defaults to pet potion thresholds', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot({ capture_only: false }));
    return json({ ok: true, areas: [] });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App client={new EngineClient('token', fetcher)} />);
  await waitFor(() => expect(screen.getByRole('img')).toBeTruthy());
  fireEvent.change(screen.getByRole('combobox', { name: 'Run mode' }), { target: { value: 'farming' } });
  expect((screen.getByLabelText('Session minutes') as HTMLInputElement).value).toBe('15');
  expect((screen.getByLabelText('Pet HP trigger %') as HTMLInputElement).value).toBe('50');
  expect((screen.getByLabelText('Pet MP trigger %') as HTMLInputElement).value).toBe('50');
  expect((screen.getByLabelText('Feed every (seconds)') as HTMLInputElement).value).toBe('');
  expect(screen.getByRole('button', { name: /Start farming$/ }).hasAttribute('disabled')).toBe(true);
});

it('offers no manual navigation mode; routes go through the path builder', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot());
    return json({ ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App client={new EngineClient('token', fetcher)} />);
  await waitFor(() => expect(screen.getByRole('img')).toBeTruthy());
  const modes = [...(screen.getByRole('combobox', { name: 'Run mode' }) as HTMLSelectElement).options].map(o => o.value);
  expect(modes).not.toContain('navigation');
  expect(screen.queryByRole('button', { name: 'Routes' })).toBeNull();
});

it('starts in full-width overview and preview mode; a tool opens and closes without input', async () => {
  const commands: string[] = [];
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot());
    const command = JSON.parse(String(options?.body)); commands.push(command.name);
    return json({ ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App client={new EngineClient('token', fetcher)} />);
  await waitFor(() => expect(screen.getByRole('img')).toBeTruthy());
  expect(screen.getByRole('combobox', { name: 'Run mode' }).getAttribute('value') ?? (screen.getByRole('combobox', { name: 'Run mode' }) as HTMLSelectElement).value).toBe('preview');
  expect(screen.queryByLabelText('Recognition tool')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Recognition' }));
  expect(screen.getByLabelText('Recognition tool')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Close tool panel' }));
  expect(screen.queryByLabelText('Recognition tool')).toBeNull();
  await waitFor(() => expect(screen.getByRole('button', { name: /Start preview$/ }).hasAttribute('disabled')).toBe(false), { timeout: 2000 });
  fireEvent.click(screen.getByRole('button', { name: /Start preview$/ }));
  await waitFor(() => expect(commands).toContain('dry_run'));
  expect(commands).not.toContain('arm');
  fireEvent.click(screen.getByRole('button', { name: 'Screenshot' }));
  await waitFor(() => expect(commands).toContain('save'));
  fireEvent.click(screen.getByRole('button', { name: 'Save last clip' }));
  await waitFor(() => expect(commands).toContain('clip'));
  fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
  await waitFor(() => expect(commands).toContain('pause'));
  fireEvent.click(screen.getByRole('button', { name: /Stop F8/ }));
  await waitFor(() => expect(commands).toContain('stop'));
});

it('blocks Start when a once-fresh displayed frame ages while status remains unchanged', async () => {
  const current = snapshot();
  let refreshing = true;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => String(url).startsWith('/api/v1/frame')
    ? new Response(new Blob(['image'])) : json({ ...current, frame: { ...current.frame,
      captured_at: refreshing ? Date.now() / 1000 : current.frame.captured_at } }));
  vi.stubGlobal('fetch', fetcher);
  render(<App client={new EngineClient('token', fetcher)} />);
  const start = screen.getByRole('button', { name: /Start preview$/ });
  await waitFor(() => expect(start.hasAttribute('disabled')).toBe(false), { timeout: 2000 });
  refreshing = false;
  await waitFor(() => expect(start.hasAttribute('disabled')).toBe(true), { timeout: 1200 });
  expect(screen.getByText('Last frame · waiting for capture')).toBeTruthy();
  expect(screen.getByRole('button', { name: /Stop F8/ }).hasAttribute('disabled')).toBe(false);
});

it('keeps the last frame mounted during same-source capture loss while blocking Start', async () => {
  let current = snapshot();
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => String(url).startsWith('/api/v1/frame')
    ? new Response(new Blob(['image'])) : json({ ...current, frame: { ...current.frame, captured_at: Date.now() / 1000 } }));
  vi.stubGlobal('fetch', fetcher);
  render(<App client={new EngineClient('token', fetcher)} />);
  const start = screen.getByRole('button', { name: /Start preview$/ });
  await waitFor(() => expect(start.hasAttribute('disabled')).toBe(false), { timeout: 2000 });
  const image = screen.getByRole('img');
  current = snapshot({ frame: { ...current.frame, id: null, captured_at: null, width: 0, height: 0, available: false } });
  await waitFor(() => expect(start.hasAttribute('disabled')).toBe(true));
  await waitFor(() => expect(screen.getByText('Last frame · waiting for capture')).toBeTruthy());
  expect(screen.getByRole('img')).toBe(image);
  expect(image.getAttribute('alt')).toBe('Last good game frame');
  expect(image.getAttribute('width')).toBe('1024');
  expect(image.getAttribute('height')).toBe('768');
  expect(start.hasAttribute('disabled')).toBe(true);
});

it('keeps preview steady through slow recognition and enables Start only after sustained freshness', async () => {
  vi.useFakeTimers();
  let sequence = 0;
  let steady = false;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
    if (String(url).startsWith('/api/v1/preview')) return new Response(new Blob(['preview']));
    const s = snapshot();
    sequence++;
    s.preview_frame = { ...s.frame, id: `preview:${sequence}`, sequence };
    if (!steady && sequence % 4 !== 1) s.frame.captured_at! -= 2;
    return json(s);
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App client={new EngineClient('token', fetcher)} />);
  const start = screen.getByRole('button', { name: /Start preview$/ });
  for (let i = 0; i < 16; i++) {
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    expect(start.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('Live picture')).toBeTruthy();
  }
  steady = true;
  await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
  expect(start.hasAttribute('disabled')).toBe(false);
  expect(fetcher.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});

it('acknowledges only the displayed alarm and provides a clipboard fallback', async () => {
  const s = snapshot({ alarm: { active: true, incident_id: 'current-alarm' } });
  const acknowledge = vi.fn();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
  render(<AlarmBanner snapshot={s} onAcknowledge={acknowledge} />);
  expect(acknowledge).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Acknowledge alarm' }));
  expect(acknowledge).toHaveBeenCalledWith('current-alarm');
  fireEvent.click(screen.getByText('Details'));
  fireEvent.click(screen.getByRole('button', { name: 'Copy alarm' }));
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Alarm details to copy' })).toBeTruthy());
});

it('shows the reload recovery above the game view when a restarted engine disables commands', async () => {
  let sessionId = 'first-session';
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => String(url).startsWith('/api/v1/frame')
    ? new Response(new Blob(['image'])) : json(snapshot({ session_id: sessionId })));
  vi.stubGlobal('fetch', fetcher);
  const client = new EngineClient('token', fetcher);
  render(<App client={client} />);
  await waitFor(() => expect(screen.getByRole('img')).toBeTruthy());
  sessionId = 'replacement-session';
  await act(async () => { await client.readStatus(); });
  expect(screen.getByRole('button', { name: /Start preview$/ }).hasAttribute('disabled')).toBe(true);
  const recovery = screen.getByRole('region', { name: 'Reconnect workspace' });
  expect(within(recovery).getByRole('button', { name: 'Reload workspace' }).hasAttribute('disabled')).toBe(false);
  expect(recovery.compareDocumentPosition(screen.getByLabelText('Live game workspace')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(fetcher.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
});

it('offers acknowledgement beside the capture failure inside the safety banner', async () => {
  const commands: { name: string; payload: Record<string, unknown> }[] = [];
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (options?.method === 'POST') { commands.push(JSON.parse(String(options.body))); return json({ acknowledged: true }); }
    return json(snapshot({ alarm: { active: true, incident_id: 'capture-failure' } }));
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App client={new EngineClient('token', fetcher)} />);
  const banner = await screen.findByRole('region', { name: 'Safety stop' });
  fireEvent.click(within(banner).getByRole('button', { name: 'Acknowledge alarm' }));
  await waitFor(() => expect(commands).toContainEqual(expect.objectContaining({ name: 'acknowledge', payload: { incident_id: 'capture-failure' } })));
});
