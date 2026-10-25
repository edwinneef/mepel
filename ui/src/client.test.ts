import { afterEach, describe, expect, it, vi } from 'vitest';
import { EngineClient } from './client';
import { deferred, json, snapshot } from './test-fixtures';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('versioned engine commands', () => {
  it('calls the default browser fetch with its global receiver', async () => {
    const browserFetch = vi.fn(function (this: unknown) {
      if (this !== globalThis) throw new TypeError('Illegal invocation');
      return Promise.resolve(json(snapshot()));
    });
    vi.stubGlobal('fetch', browserFetch);
    const client = new EngineClient('token');
    await client.readStatus();
    expect(client.getState().connected).toBe(true);
    expect(browserFetch.mock.contexts[0]).toBe(globalThis);
  });

  it('fetches fresh context, sends a unique command once, and preserves server errors', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json(snapshot()))
      .mockResolvedValueOnce(json({ error: 'Capture-only session' }, 400));
    const client = new EngineClient('local-token', fetcher);
    await expect(client.command('arm')).rejects.toThrow('Capture-only session');
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/status');
    const options = fetcher.mock.calls[1][1]!;
    const envelope = JSON.parse(String(options.body));
    expect(envelope).toMatchObject({ schema_version: 1, session_id: 'test-session', command_epoch: 1, expected_frame_id: 'test-session:1', name: 'arm' });
    expect(envelope.command_id.length).toBeGreaterThan(8);
    expect(options.headers).toMatchObject({ 'X-Debug-Token': 'local-token' });
  });

  it('Stop bypasses a hanging status request and cancels the pending Start', async () => {
    const waiting = deferred<Response>();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json(snapshot()))
      .mockReturnValueOnce(waiting.promise).mockResolvedValueOnce(json({ ok: true }));
    const client = new EngineClient('token', fetcher);
    await client.readStatus();
    const start = client.command('dry_run');
    const canceled = expect(start).rejects.toThrow('Canceled by Stop');
    await client.command('stop');
    expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body)).name).toBe('stop');
    waiting.resolve(json(snapshot()));
    await canceled;
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(client.getState().busy).toBe(false);
  });

  it('Stop is still sent before any snapshot is available', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ ok: true }));
    await new EngineClient('token', fetcher).command('stop');
    expect(fetcher.mock.calls[0][0]).toBe('/api/stop');
  });

  it('does not allow an older status response to replace a newer session', async () => {
    const waiting = deferred<Response>();
    const fetcher = vi.fn<typeof fetch>().mockReturnValueOnce(waiting.promise)
      .mockResolvedValueOnce(json(snapshot({ session_id: 'new-session' })));
    const client = new EngineClient('token', fetcher);
    const old = client.readStatus();
    await client.readStatus();
    waiting.resolve(json(snapshot())); await old;
    expect(client.getState().snapshot?.session_id).toBe('new-session');
  });

  it('a new engine session cancels a pending command instead of automatically resuming', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json(snapshot()))
      .mockResolvedValueOnce(json(snapshot({ session_id: 'replacement' })));
    const client = new EngineClient('token', fetcher);
    await client.readStatus();
    await expect(client.command('arm')).rejects.toThrow('new session');
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(client.getState().notice).toContain('Input stays stopped');
  });
});
