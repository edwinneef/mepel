import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { EngineClient } from './client';
import { App } from './App';
import { areaErrors, drawArea, graphWarnings, newArea, removeAreaItem, toArea, toView } from './area';
import { useAreaEditor } from './useAreaEditor';
import { deferred, json, snapshot } from './test-fixtures';
import type { AreaProfile, AreaView } from './contracts';
import { AreaEditor } from './AreaEditor';

const reference: AreaView = { id: 'view1', name: 'View 1', width: 800, height: 400, origin: { x: 0, y: 0 }, scale: 1, image: 'a'.repeat(64) };

beforeEach(() => {
  vi.stubGlobal('Image', class { src = ''; decode = async () => {}; });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  Object.defineProperty(window, 'PointerEvent', { configurable: true, value: MouseEvent });
  HTMLElement.prototype.setPointerCapture = vi.fn();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('uses the explicit view transform for native drawing and locks ropes to a vertical line', () => {
  const view = { ...reference, origin: { x: -100, y: 50 }, scale: 2 };
  expect(toArea({ x: 200, y: 100 }, view)).toEqual({ x: 0, y: 100 });
  expect(toView({ x: 0, y: 100 }, view)).toEqual({ x: 200, y: 100 });
  const platform = drawArea(newArea(), view, 'platform', { x: 200, y: 100 }, { x: 600, y: 100 }).profile;
  expect(platform.platforms[0]).toMatchObject({ start: { x: 0, y: 100 }, end: { x: 200, y: 100 } });
  const rope = drawArea(platform, view, 'rope', { x: 300, y: 100 }, { x: 350, y: 300 }).profile;
  expect(rope.ropes[0]).toMatchObject({ start: { x: 50, y: 100 }, end: { x: 50, y: 200 } });
});

it('keeps directed graph warnings separate from boundary errors and removes incident links', () => {
  const profile = { ...newArea(), views: [reference], boundary: { x: 0, y: 0, width: 800, height: 400 },
    platforms: [{ id: 'p1', start: { x: 10, y: 100 }, end: { x: 100, y: 100 } }, { id: 'p2', start: { x: 200, y: 100 }, end: { x: 300, y: 100 } }] };
  expect(areaErrors(profile)).toEqual([]);
  expect(graphWarnings(profile)[0]).toContain('p2');
  profile.links = [{ id: 'link1', from: 'p1', to: 'p2', kind: 'jump' }];
  expect(graphWarnings(profile)).toEqual([]);
  expect(removeAreaItem(profile, 'p2').links).toEqual([]);
  profile.zones = [{ id: 'avoid1', kind: 'avoid', rect: { x: 790, y: 0, width: 20, height: 20 } }];
  expect(areaErrors(profile)[0]).toContain('outside');
});

it('requires confirmed stopped editing before creating or mutating a draft', async () => {
  const stopped = deferred<{ editing: boolean }>();
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockImplementation(async name => name === 'area_begin' ? stopped.promise : { editing: false });
  const { result } = renderHook(() => useAreaEditor(client, 'session'));
  let creating!: Promise<void>;
  act(() => { creating = result.current.create(); });
  expect(command.mock.calls[0][0]).toBe('area_begin');
  expect(result.current.draft).toBeNull();
  act(() => result.current.mutate(profile => ({ ...profile, name: 'Should not change' })));
  expect(result.current.error).toContain('Begin area editing first');
  await act(async () => { stopped.resolve({ editing: true }); await creating; });
  expect(result.current.draft?.name).toBe('New hunting area');
  await act(async () => { await result.current.end(); });
  act(() => result.current.mutate(profile => ({ ...profile, name: 'Still blocked' })));
  expect(result.current.draft?.name).toBe('New hunting area');
  expect(command.mock.calls.some(([name]) => name === 'arm' || name === 'probe')).toBe(false);
});

it('ignores pre-Begin status but revokes editing on a later engine update without losing the draft', async () => {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({ editing: true });
  vi.spyOn(client, 'readStatus').mockResolvedValue(snapshot({ area_editing: true, command_epoch: 6 }));
  let server = { editing: false, epoch: 5 };
  const { result, rerender } = renderHook(() => useAreaEditor(client, 'session', server.editing, server.epoch));
  await act(async () => { await result.current.create(); });
  expect(result.current.editing).toBe(true);
  act(() => result.current.mutate(profile => ({ ...profile, name: 'Preserved hunting area' })));
  // A delayed status from before Begin has no authority over the confirmed epoch.
  act(() => { server = { editing: false, epoch: 4 }; rerender(); });
  expect(result.current.editing).toBe(true);
  act(() => { server = { editing: true, epoch: 6 }; rerender(); });
  act(() => { server = { editing: false, epoch: 7 }; rerender(); });
  expect(result.current.editing).toBe(false);
  expect(result.current.draft?.name).toBe('Preserved hunting area');
  expect(result.current.dirty).toBe(true);
  act(() => result.current.mutate(profile => ({ ...profile, name: 'Blocked edit' })));
  expect(result.current.draft?.name).toBe('Preserved hunting area');
  expect(result.current.error).toContain('Begin area editing first');
  render(<AreaEditor workspace={result.current} active={false} connected disabled={false} />);
  expect(screen.getByRole('button', { name: 'Begin editing · stop input' }).hasAttribute('disabled')).toBe(false);
  expect(command.mock.calls.some(([name]) => name === 'arm' || name === 'probe')).toBe(false);
});

it('retains unsaved changes and errors when saving fails, then loads server revisions after an explicit discard', async () => {
  const saved = { ...newArea(), name: 'Saved area', revision: 3, views: [reference], boundary: { x: 0, y: 0, width: 800, height: 400 } };
  let conflict = true;
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockImplementation(async name => {
    if (name === 'area_begin') return { editing: true };
    if (name === 'area_capture') return { view: reference };
    if (name === 'area_load') return { profile: saved, warnings: ['Review disconnected geometry'] };
    if (name === 'area_save' && conflict) throw new Error('Revision conflict; saved file changed');
    return { profile: { ...saved, revision: 4 }, warnings: [] };
  });
  const { result } = renderHook(() => useAreaEditor(client, 'session'));
  await act(async () => { await result.current.create(); });
  await act(async () => { await result.current.capture(); });
  expect(result.current.draft?.boundary).toEqual({ x: 0, y: 0, width: 800, height: 400 });
  act(() => result.current.mutate(profile => ({ ...profile, name: 'My unsaved area' })));
  await act(async () => { await result.current.save(); });
  expect(result.current.error).toContain('Revision conflict');
  expect(result.current.dirty).toBe(true);
  expect(result.current.draft?.name).toBe('My unsaved area');
  await act(async () => { await result.current.load(saved.id); });
  expect(command.mock.calls.some(([name]) => name === 'area_load')).toBe(false);
  await act(async () => { await result.current.confirmDiscard(); });
  expect(result.current.draft?.revision).toBe(3);
  expect(result.current.error).toBe('');
  act(() => result.current.mutate(profile => ({ ...profile, name: 'Revised' })));
  conflict = false;
  await act(async () => { await result.current.save(); });
  expect(result.current.draft?.revision).toBe(4);
  expect(result.current.dirty).toBe(false);
});

it('draws scaled geometry, keeps a closed-tool draft, adds a link and saves without gameplay commands', async () => {
  const commands: Array<{ name: string; payload: Record<string, unknown> }> = [];
  let editing = false;
  let saved: AreaProfile | null = null;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['live']));
    if (url === '/api/v1/status') return json(snapshot({ area_editing: editing }));
    const command = JSON.parse(String(options?.body)); commands.push(command);
    if (command.name === 'area_list') return json({ areas: saved ? [{ id: saved.id, name: saved.name, revision: saved.revision }] : [], errors: [] });
    if (command.name === 'area_begin') { editing = true; return json({ editing }); }
    if (command.name === 'area_capture') return json({ view: reference });
    if (command.name === 'area_save') { saved = { ...command.payload.profile, revision: 1 }; return json({ profile: saved, warnings: [] }); }
    if (command.name === 'area_end') { editing = false; return json({ editing }); }
    return json({ ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App client={new EngineClient('token', fetcher)} />);
  await waitFor(() => expect(screen.getByRole('img')).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Navigation' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'New area' }).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'New area' }));
  await waitFor(() => expect(screen.getByLabelText('Area name')).toBeTruthy());
  expect(screen.getByRole('button', { name: /Start$/ }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Capture reference view' }));
  await waitFor(() => expect(screen.getByRole('img', { name: 'Area reference: View 1' })).toBeTruthy());
  const image = screen.getByRole('img', { name: 'Area reference: View 1' });
  fireEvent.load(image);
  vi.spyOn(image, 'getBoundingClientRect').mockReturnValue(new DOMRect(20, 30, 400, 200));
  fireEvent.click(screen.getByRole('button', { name: 'Platform' }));
  const surface = image.parentElement!;
  for (const [from, to] of [[70, 220], [270, 370]]) {
    fireEvent.pointerDown(surface, { clientX: from, clientY: 130, pointerId: 1 });
    fireEvent.pointerUp(surface, { clientX: to, clientY: 130, pointerId: 1 });
  }
  fireEvent.change(screen.getByLabelText('Area name'), { target: { value: 'My taught area' } });
  fireEvent.click(screen.getByRole('button', { name: 'Close tool panel' }));
  expect(screen.queryByRole('textbox', { name: 'Area name' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Navigation' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save area' }).hasAttribute('disabled')).toBe(false));
  expect((screen.getByLabelText('Area name') as HTMLInputElement).value).toBe('My taught area');
  const from = screen.getByLabelText('Link from') as HTMLSelectElement;
  const to = screen.getByLabelText('Link to') as HTMLSelectElement;
  expect(from.options.length).toBe(3);
  fireEvent.change(from, { target: { value: from.options[1].value } });
  fireEvent.change(to, { target: { value: to.options[2].value } });
  fireEvent.click(screen.getByRole('button', { name: 'Add directed link' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save area' }));
  await waitFor(() => expect(commands.some(command => command.name === 'area_save')).toBe(true));
  const profile = commands.find(command => command.name === 'area_save')!.payload.profile as AreaProfile;
  expect(profile.platforms.map(item => [item.start, item.end])).toEqual([
    [{ x: 100, y: 200 }, { x: 400, y: 200 }], [{ x: 500, y: 200 }, { x: 700, y: 200 }],
  ]);
  expect(profile.links[0]).toMatchObject({ from: profile.platforms[0].id, to: profile.platforms[1].id, kind: 'walk' });
  expect(commands.some(command => command.name === 'arm' || command.name === 'probe' || command.name === 'dry_run')).toBe(false);
});

it('sends existing views with a capture and shows where the new view was aligned', async () => {
  const client = new EngineClient('token', vi.fn());
  const second: AreaView = { ...reference, id: 'view2', name: 'View 2', image: 'b'.repeat(64), origin: { x: 300, y: 0 } };
  const command = vi.spyOn(client, 'command').mockImplementation(async (name, payload) => {
    if (name === 'area_begin') return { editing: true };
    if (name === 'area_capture') return (payload as { align: unknown[] }).align.length
      ? { view: second, alignment: { aligned: true, view_id: 'view1', origin: { x: 300, y: 0 }, scale: 1, agree: 7, patches: 9, reason: '7 of 9 textured patches agree' } }
      : { view: reference, alignment: { aligned: false, view_id: null, origin: null, scale: null, agree: 0, patches: 0, reason: 'No earlier view to align with' } };
    return {};
  });
  const { result } = renderHook(() => useAreaEditor(client, 'session'));
  await act(async () => { await result.current.create(); });
  await act(async () => { await result.current.capture(); });
  await act(async () => { await result.current.capture(); });
  expect(command).toHaveBeenLastCalledWith('area_capture', { align: [{ id: 'view1', image: reference.image, origin: { x: 0, y: 0 }, scale: 1 }] });
  expect(result.current.draft?.views.map(view => view.origin.x)).toEqual([0, 300]);
  render(<AreaEditor workspace={result.current} active={false} connected disabled={false} />);
  expect(screen.getByText(/Auto-aligned to View 1: origin 300.0, 0.0 · 7 of 9 textured patches agree/)).toBeTruthy();
});
