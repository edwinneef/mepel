import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PlayerCapture } from './PlayerCapture';
import { EngineClient } from './client';
import { snapshot } from './test-fixtures';
afterEach(cleanup);
it('starts a shared bounded collection without a rectangle and supports cancellation', async () => {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({});
  const poses = { enabled: false, identity: '', outfit: '', identities: ['name'], saved: 0, duplicates: 0, rejected: 0, pending: 0, limit: 32, reason: 'Off' };
  const props = { snapshot: snapshot({ pose_collection: poses }), client, act: async (op: () => Promise<unknown>) => { await op(); }, disabled: false };
  const view = render(<PlayerCapture {...props} />);
  fireEvent.click(screen.getByText('Capture player screenshots'));
  await waitFor(() => expect(command).toHaveBeenCalledWith('pose_collection', expect.objectContaining({ enabled: true, identity: 'name' })));
  view.rerender(<PlayerCapture {...props} snapshot={snapshot({ pose_collection: { ...poses, enabled: true } })} />);
  fireEvent.click(screen.getByText('Cancel screenshot capture'));
  await waitFor(() => expect(command).toHaveBeenCalledWith('pose_collection', { enabled: false }));
});
it('requires a taught identity', () => {
  render(<PlayerCapture snapshot={snapshot()} client={new EngineClient('token', vi.fn())} act={async op => { await op(); }} disabled={false} />);
  expect((screen.getByText('Capture player screenshots') as HTMLButtonElement).disabled).toBe(true);
});

it('selects taught names with widget buttons instead of a native popup', async () => {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({});
  const poses = { enabled: false, identity: '', outfit: '', identities: ['alice', 'bob'], saved: 0, duplicates: 0, rejected: 0, pending: 0, limit: 32, reason: 'Off' };
  render(<PlayerCapture snapshot={snapshot({ pose_collection: poses })} client={client} act={async op => { await op(); }} disabled={false} />);
  expect(screen.queryByRole('combobox')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Select taught name' }));
  fireEvent.click(screen.getByRole('button', { name: 'Taught name 2' }));
  expect(screen.queryByRole('group', { name: 'Taught names' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Taught name 2' }).getAttribute('aria-expanded')).toBe('false');
  fireEvent.click(screen.getByText('Capture player screenshots'));
  await waitFor(() => expect(command).toHaveBeenCalledWith('pose_collection', expect.objectContaining({ enabled: true, identity: 'bob' })));
});

it('shows and saves in-game names for taught tags', async () => {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({});
  const poses = { enabled: false, identity: '', outfit: '', identities: ['aaaaaa1', 'bbbbbb2', 'cccccc3'],
    labels: { aaaaaa1: 'ScrollAddict', bbbbbb2: 'ScrollAddict' }, saved: 0, duplicates: 0, rejected: 0, pending: 0, limit: 32, reason: 'Off' };
  render(<PlayerCapture snapshot={snapshot({ pose_collection: poses })} client={client} act={async op => { await op(); }} disabled={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Select taught name' }));
  // One entry per character, however many tags were taught for it.
  expect(screen.getAllByRole('button', { name: /ScrollAddict/ })).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Taught name 3' }));
  const input = screen.getByLabelText('In-game name') as HTMLInputElement;
  expect(input.value).toBe('');
  fireEvent.change(input, { target: { value: 'Bowcaine' } });
  fireEvent.click(screen.getByText('Save name'));
  await waitFor(() => expect(command).toHaveBeenCalledWith('nametag_label', { identity: 'cccccc3', label: 'Bowcaine' }));
});

it('selects the character being tracked by default and names all of its tags together', async () => {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({});
  const poses = { enabled: false, identity: 'cccccc3', outfit: '', identities: ['aaaaaa1', 'bbbbbb2', 'cccccc3'],
    labels: { aaaaaa1: 'ScrollAddict', bbbbbb2: 'ScrollAddict', cccccc3: 'Bowcaine' }, saved: 0, duplicates: 0, rejected: 0, pending: 0, limit: 32, reason: 'Off' };
  const base = snapshot({ pose_collection: poses });
  const current = { ...base, player_tracking: { state: 'confirmed' as const, predicted: null, observed: null, search: null,
    confidence: 1, identity: 'nametag:bbbbbb2', since_confirmed: 0 } };
  render(<PlayerCapture snapshot={current} client={client} act={async op => { await op(); }} disabled={false} />);
  expect(screen.getByRole('button', { name: 'ScrollAddict' })).toBeTruthy();
  fireEvent.click(screen.getByText('Capture player screenshots'));
  await waitFor(() => expect(command).toHaveBeenCalledWith('pose_collection', expect.objectContaining({ identity: 'bbbbbb2' })));
  fireEvent.change(screen.getByLabelText('In-game name'), { target: { value: 'Scroll' } });
  fireEvent.click(screen.getByText('Save name'));
  await waitFor(() => expect(command).toHaveBeenCalledWith('nametag_label', { identity: 'bbbbbb2', label: 'Scroll' }));
  expect(command).toHaveBeenCalledWith('nametag_label', { identity: 'aaaaaa1', label: 'Scroll' });
  expect(command).not.toHaveBeenCalledWith('nametag_label', expect.objectContaining({ identity: 'cccccc3' }));
});

it('shows rejection reasons after a zero-screenshot capture ends', () => {
  const poses = { enabled: false, identity: 'alice', outfit: 'one', identities: ['alice'], saved: 0, duplicates: 0, rejected: 12, pending: 0, limit: 32, reason: 'Capture complete', last_rejection: 'Nearby appearance overlaps collection', rejection_reasons: { 'Nearby appearance overlaps collection': 12 } };
  render(<PlayerCapture snapshot={snapshot({ pose_collection: poses })} client={new EngineClient('token', vi.fn())} act={async op => { await op(); }} disabled={false} />);
  expect(screen.getByText('12 frames rejected. Last: Nearby appearance overlaps collection')).toBeTruthy();
  expect(screen.getByText('Nearby appearance overlaps collection: 12')).toBeTruthy();
});

it('selects multiple examples, excludes added ones and sends one batch', async () => {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({});
  const poses = { enabled: false, identity: 'alice', outfit: 'one', identities: ['alice'], saved: 3, duplicates: 0, rejected: 0, pending: 0, limit: 32, reason: 'Capture complete', candidates: [{ id: 'one', crop: '' }, { id: 'two', crop: '' }, { id: 'three', crop: '', added: true }] };
  const props = { snapshot: snapshot({ pose_collection: poses }), client, act: async (op: () => Promise<unknown>) => { await op(); }, disabled: false };
  const view = render(<PlayerCapture {...props} />);
  fireEvent.click(screen.getByText('Review screenshots'));
  fireEvent.click(screen.getByLabelText('Select all'));
  expect(screen.getByText('2 selected')).toBeTruthy();
  expect((screen.getByLabelText('Select screenshot 3') as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByText('Add selected to player examples'));
  await waitFor(() => expect(command).toHaveBeenCalledWith('pose_collection', { use_selected: ['one', 'two'] }));
  view.rerender(<PlayerCapture {...props} snapshot={snapshot({ pose_collection: { ...poses, candidates: poses.candidates.map(candidate => ({ ...candidate, added: true })) } })} />);
  expect(screen.getByText('0 selected')).toBeTruthy();
  expect(screen.getAllByText('Already added')).toHaveLength(3);
});
