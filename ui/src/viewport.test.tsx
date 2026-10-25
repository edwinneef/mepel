import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { GameViewport } from './GameViewport';
import { EngineClient } from './client';
import { useViewport } from './useViewport';
import { deferred, json, snapshot } from './test-fixtures';

beforeEach(() => {
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

it('clears old source bytes on frame invalidation and retries a superseded frame on the next status', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response(null, { status: 409 }))
    .mockResolvedValue(new Response(new Blob(['frame'])));
  vi.stubGlobal('fetch', fetcher);
  const client = new EngineClient('token', fetcher);
  let current = snapshot();
  const { result, rerender } = renderHook(() => useViewport(client, current, true));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  await act(async () => { current = snapshot(); rerender(); });
  await waitFor(() => expect(result.current.image?.key).toBe('test-session:1'));
  await act(async () => {
    current = snapshot({ frame: { ...current.frame, id: null, available: false } }); rerender();
  });
  expect(result.current.image).toBeNull();
});
