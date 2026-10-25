import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from './App';
import { EngineClient } from './client';
import { AlarmBanner } from './AlarmBanner';
import { json, snapshot } from './test-fixtures';

beforeEach(() => {
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

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
  expect(screen.queryByLabelText('Tracking tool')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Tracking' }));
  expect(screen.getByLabelText('Tracking tool')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Close tool panel' }));
  expect(screen.queryByLabelText('Tracking tool')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: /Start$/ }));
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
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => String(url).startsWith('/api/v1/frame')
    ? new Response(new Blob(['image'])) : json(current));
  vi.stubGlobal('fetch', fetcher);
  render(<App client={new EngineClient('token', fetcher)} />);
  const start = screen.getByRole('button', { name: /Start$/ });
  await waitFor(() => expect(start.hasAttribute('disabled')).toBe(false));
  await waitFor(() => expect(start.hasAttribute('disabled')).toBe(true), { timeout: 1200 });
  expect(screen.getByText('Waiting for fresh frame')).toBeTruthy();
  expect(screen.getByRole('button', { name: /Stop F8/ }).hasAttribute('disabled')).toBe(false);
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
