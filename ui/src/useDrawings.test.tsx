import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useDrawings } from './useDrawings';
import type { LiveDetections } from './contracts';

const packet = (sequence = 1): LiveDetections => ({ display: true, player: null,
  frame: { source_id: 'engine:source:1', id: `frame:${sequence}`, sequence, captured_at: Date.now() / 1000,
    width: 1366, height: 768, available: true, age_ms: 0 } });
const response = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(10000); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it('keeps only one request in flight and clears a stalled stream by 500 ms', async () => {
  const first = packet();
  const fetcher = vi.fn().mockResolvedValueOnce(response(first)).mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal('fetch', fetcher);
  const { result } = renderHook(() => useDrawings(true, 'engine'));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(result.current?.frame.id).toBe(first.frame.id);
  await act(async () => { await vi.advanceTimersByTimeAsync(499); });
  expect(fetcher).toHaveBeenCalledTimes(2);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(result.current).toBeNull();
});

it('never revives semantic fallback after invalidation or failure', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(response(packet())).mockResolvedValueOnce(response(null))
    .mockRejectedValue(new Error('offline'));
  vi.stubGlobal('fetch', fetcher);
  const { result } = renderHook(() => useDrawings(true, 'engine'));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(result.current).not.toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(34); });
  expect(result.current).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(34); });
  expect(result.current).toBeNull();
});

it('rejects prior-session packets and cancels in-flight work on unmount', async () => {
  let signal: AbortSignal | undefined;
  const fetcher = vi.fn().mockResolvedValueOnce(response(packet())).mockImplementation((_url, options) => {
    signal = options.signal; return new Promise(() => {});
  });
  vi.stubGlobal('fetch', fetcher);
  const { result, unmount } = renderHook(() => useDrawings(true, 'new-engine'));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(result.current).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(34); });
  unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it('allows the legacy path only while the endpoint is unsupported', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 404 })));
  const { result } = renderHook(() => useDrawings(true, 'engine'));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(result.current).toBeUndefined();
});
