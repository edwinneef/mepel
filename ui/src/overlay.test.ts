import { describe, expect, it, vi } from 'vitest';
import { OverlayClient, freshDetections, isRunning } from './overlay';
import type { Snapshot } from './contracts';

describe('overlay controls', () => {
  it('selects gameplay commands without submitting input from settings', async () => {
    const fetcher = vi.fn();
    const client = new OverlayClient('token', fetcher);
    client.select = vi.fn();
    await client.command('probe', { action: 'jump' });
    await client.command('arm');
    await client.command('nav_go', { target: 'p2', opt_in: true });
    expect(fetcher).not.toHaveBeenCalled();
    expect(client.select).toHaveBeenCalledTimes(3);
  });
  it('does not display stale detections as live', () => {
    const snapshot = { frame: { available: true, captured_at: 10 } } as Snapshot;
    expect(freshDetections(snapshot, true, 11000)).toBe(true);
    expect(freshDetections(snapshot, true, 12000)).toBe(false);
    expect(freshDetections(snapshot, false, 11000)).toBe(false);
    expect(freshDetections(snapshot, true, 9000)).toBe(false);
  });
  it('derives On from engine state, not the last requested toggle', () => {
    const snapshot = { mode: 'capture', alarm: { active: false }, autopotter: { enabled: false } } as Snapshot;
    expect(isRunning(snapshot)).toBe(false);
    expect(isRunning({ ...snapshot, mode: 'live' })).toBe(true);
    expect(isRunning({ ...snapshot, mode: 'probe_confirm' })).toBe(false);
    expect(isRunning({ ...snapshot, mode: 'live', alarm: { active: true } })).toBe(false);
  });
});
