import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { GameViewport } from './GameViewport';
import { EngineClient } from './client';
import { useViewport } from './useViewport';
import { deferred, json, snapshot } from './test-fixtures';

beforeEach(() => {
  vi.stubGlobal('Image', class { src = ''; decode = async () => {}; });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:frame') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  Object.defineProperty(window, 'PointerEvent', { configurable: true, value: MouseEvent });
  HTMLElement.prototype.setPointerCapture = vi.fn();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('maps a CSS-scaled drag to clamped original screenshot pixels', () => {
  const selected = vi.fn();
  render(<GameViewport image={{ url: 'blob:test', width: 1024, height: 768, key: 'test' }} frozen selection={null} onSelection={selected} />);
  const image = screen.getByRole('img');
  vi.spyOn(image, 'getBoundingClientRect').mockReturnValue(new DOMRect(20, 30, 512, 384));
  const surface = image.parentElement!;
  fireEvent.pointerDown(surface, { clientX: 120, clientY: 80, pointerId: 1 });
  fireEvent.pointerMove(surface, { clientX: 320, clientY: 230, pointerId: 1 });
  fireEvent.pointerUp(surface, { clientX: 320, clientY: 230, pointerId: 1 });
  expect(selected).toHaveBeenLastCalledWith({ x: 200, y: 100, width: 400, height: 300 });
});

it('keeps native selection coordinates at 200 percent and in expanded view', () => {
  const selected = vi.fn();
  const selection = { x: 200, y: 100, width: 400, height: 300 };
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')); };
  render(<GameViewport image={{ url: 'blob:test', width: 1024, height: 768, key: 'test' }} frozen selection={selection} onSelection={selected} />);
  fireEvent.click(screen.getByRole('button', { name: '200%' }));
  const image = screen.getByRole('img');
  vi.spyOn(image, 'getBoundingClientRect').mockReturnValue(new DOMRect(20, 30, 2048, 1536));
  fireEvent.pointerDown(image.parentElement!, { clientX: 420, clientY: 230, pointerId: 1 });
  fireEvent.pointerUp(image.parentElement!, { clientX: 1220, clientY: 830, pointerId: 1 });
  expect(selected).toHaveBeenLastCalledWith(selection);
  fireEvent.click(screen.getByRole('button', { name: 'Expand game' }));
  const expanded = screen.getByRole('dialog', { name: 'Expanded game' });
  expect(expanded.querySelector('.selection-layer rect')?.getAttribute('x')).toBe('200');
  fireEvent.click(screen.getByRole('button', { name: 'Close expanded game' }));
  expect(screen.queryByRole('dialog')).toBeNull();
});

it('an old live fetch cannot replace a newer frozen selection frame', async () => {
  const old = deferred<Response>();
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
    if (String(url).startsWith('/api/v1/frame')) return old.promise;
    if (String(url).startsWith('/frame.png')) return new Response(new Blob(['frozen']));
    if (url === '/api/v1/status') return json(snapshot());
    return json({ id: 'frozen-id', width: 1024, height: 768 });
  });
  vi.stubGlobal('fetch', fetcher);
  const client = new EngineClient('token', fetcher);
  const { result } = renderHook(() => useViewport(client, snapshot(), true));
  await act(async () => { await result.current.freeze(); });
  expect(result.current.frozen?.id).toBe('frozen-id');
  expect(result.current.image?.key).toBe('frozen-id');
  await act(async () => { old.resolve(new Response(new Blob(['old-live']))); });
  expect(result.current.image?.key).toBe('frozen-id');
});

it('retains the last good image and its dimensions through same-source capture loss', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(new Blob(['good-frame'])));
  vi.stubGlobal('fetch', fetcher);
  const client = new EngineClient('token', fetcher);
  let current = snapshot();
  const { result, rerender } = renderHook(() => useViewport(client, current, true));
  await waitFor(() => expect(result.current.image?.key).toBe('test-session:1'));
  const goodImage = result.current.image;
  await act(async () => {
    current = snapshot({ frame: { ...current.frame, id: null, width: 0, height: 0, available: false } });
    rerender();
  });
  expect(result.current.image).toBe(goodImage);
  expect(result.current.image).toMatchObject({ width: 1024, height: 768 });
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
});

it('retries a superseded frame on the next status', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response(null, { status: 409 }))
    .mockResolvedValue(new Response(new Blob(['frame'])));
  vi.stubGlobal('fetch', fetcher);
  const client = new EngineClient('token', fetcher);
  let current = snapshot();
  const { result, rerender } = renderHook(() => useViewport(client, current, true));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  await act(async () => { current = snapshot(); rerender(); });
  await waitFor(() => expect(result.current.image?.key).toBe('test-session:1'));
});

it('keeps the displayed frame until its replacement has decoded', async () => {
  const ready = deferred<void>();
  const decode = vi.fn().mockResolvedValueOnce(undefined).mockImplementation(() => ready.promise);
  vi.stubGlobal('Image', class { src = ''; decode = decode; });
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response(new Blob(['frame'])));
  vi.stubGlobal('fetch', fetcher);
  const client = new EngineClient('token', fetcher);
  let current = snapshot();
  const { result, rerender } = renderHook(() => useViewport(client, current, true));
  await waitFor(() => expect(result.current.image?.key).toBe('test-session:1'));
  const displayed = result.current.image;
  await act(async () => {
    current = snapshot({ frame: { ...current.frame, id: 'test-session:2' } });
    rerender();
  });
  await waitFor(() => expect(decode).toHaveBeenCalledTimes(2));
  expect(result.current.image).toBe(displayed);
  await act(async () => { ready.resolve(); });
  await waitFor(() => expect(result.current.image?.key).toBe('test-session:2'));
});

it('displays a loaded image even when a hidden tab defers decode', async () => {
  vi.stubGlobal('Image', class {
    onload: (() => void) | null = null;
    set src(_value: string) { queueMicrotask(() => this.onload?.()); }
    decode = () => new Promise<void>(() => {});
  });
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response(new Blob(['frame'])));
  vi.stubGlobal('fetch', fetcher);
  const { result } = renderHook(() => useViewport(new EngineClient('token', fetcher), snapshot(), true));
  await waitFor(() => expect(result.current.image?.key).toBe('test-session:1'));
});

it('clears the image and frozen selection when the capture source actually changes', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
    if (String(url).startsWith('/api/v1/frame') || String(url).startsWith('/frame.png')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot());
    return json({ id: 'frozen-id', width: 1024, height: 768 });
  });
  vi.stubGlobal('fetch', fetcher);
  const client = new EngineClient('token', fetcher);
  let current = snapshot();
  const { result, rerender } = renderHook(() => useViewport(client, current, true));
  await act(async () => { await result.current.freeze(); });
  await act(async () => { result.current.setSelection({ x: 10, y: 20, width: 30, height: 40 }); });
  expect(result.current.selected().id).toBe('frozen-id');
  await act(async () => {
    current = snapshot({ frame: { ...current.frame, source_id: 'new-source', id: null, available: false } });
    rerender();
  });
  expect(result.current.image).toBeNull();
  expect(result.current.frozen).toBeNull();
  expect(result.current.selection).toBeNull();
});

it('rejects a late frozen response after switching sources', async () => {
  const frozen = deferred<Response>();
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
    if (String(url).startsWith('/frame.png')) return frozen.promise;
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot());
    return json({ id: 'old-source-frozen', width: 1024, height: 768 });
  });
  vi.stubGlobal('fetch', fetcher);
  const client = new EngineClient('token', fetcher);
  let current = snapshot();
  const { result, rerender } = renderHook(() => useViewport(client, current, true));
  let freezing!: Promise<void>;
  act(() => { freezing = result.current.freeze(); });
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).startsWith('/frame.png'))).toBe(true));
  await act(async () => {
    current = snapshot({ frame: { ...current.frame, source_id: 'new-source', id: null, available: false } });
    rerender();
  });
  await act(async () => { frozen.resolve(new Response(new Blob(['old-frozen']))); await freezing; });
  expect(result.current.image).toBeNull();
  expect(result.current.frozen).toBeNull();
});
