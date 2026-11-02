import type { CommandEnvelope, Snapshot } from './contracts';

export interface ClientState {
  snapshot: Snapshot | null;
  connected: boolean;
  busy: boolean;
  error: string;
  notice: string;
  needsReload: boolean;
  process: 'running' | 'restarting' | 'stopping' | 'stopped';
}

type Fetch = typeof fetch;

export class EngineClient {
  private state: ClientState = {
    snapshot: null, connected: false, busy: false, error: '', notice: '', needsReload: false, process: 'running',
  };
  private listeners = new Set<() => void>();
  private generation = 0;
  private requestSequence = 0;
  private appliedSequence = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private pollInFlight = false;
  protected pollInterval = 250;

  constructor(
    private readonly token: string,
    private readonly fetcher: Fetch = globalThis.fetch.bind(globalThis),
    private readonly reload: () => void = () => location.reload(),
  ) {}

  getState = (): ClientState => this.state;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private update(value: Partial<ClientState>): void {
    this.state = { ...this.state, ...value };
    this.listeners.forEach(listener => listener());
  }

  message(notice: string): void { this.update({ notice, error: '' }); }
  fail(error: unknown): void {
    this.update({ error: error instanceof Error ? error.message : String(error), notice: '' });
  }

  async readStatus(): Promise<Snapshot> {
    const sequence = ++this.requestSequence;
    const response = await this.fetcher('/api/v1/status', {
      cache: 'no-store', signal: AbortSignal.timeout(2000),
    });
    if (!response.ok) throw new Error(`Cannot read the engine (${response.status})`);
    const snapshot: Snapshot = await response.json();
    if (snapshot.schema_version !== 1 || !snapshot.session_id || !snapshot.frame
      || typeof snapshot.frame.source_id !== 'string' || !snapshot.readiness) {
      throw new Error('The engine needs the workspace update. Reload after restarting it.');
    }
    if (sequence >= this.appliedSequence) {
      this.appliedSequence = sequence;
      const previous = this.state.snapshot;
      const changed = previous !== null && previous.session_id !== snapshot.session_id;
      if (changed) this.generation += 1;
      this.update({
        snapshot, connected: true,
        ...(changed ? { busy: false, needsReload: true, notice: 'New engine session. Input stays stopped. Reload this workspace to reconnect.' } : {}),
      });
    }
    return snapshot;
  }

  start(): () => void {
    this.running = true;
    void this.poll();
    return () => {
      this.running = false;
      if (this.timer) clearTimeout(this.timer);
    };
  }

  private async poll(): Promise<void> {
    if (!this.running || this.pollInFlight || this.state.process !== 'running') return;
    this.pollInFlight = true;
    try {
      await this.readStatus();
    } catch (error) {
      this.fail(error);
      this.update({ connected: false });
    } finally {
      this.pollInFlight = false;
      if (this.running && this.state.process === 'running') {
        this.timer = setTimeout(() => void this.poll(), this.pollInterval);
      }
    }
  }

  async command<T = unknown>(name: string, payload: Record<string, unknown> = {}): Promise<T> {
    const urgent = name === 'stop' || name === 'pause';
    if (!urgent && this.state.needsReload) throw new Error('Reload the workspace to reconnect to the new engine session');
    if (!urgent && (this.state.busy || this.state.process !== 'running')) {
      throw new Error('Wait for the current operation to finish. Stop remains available.');
    }
    if (urgent) this.generation += 1;
    const generation = this.generation;
    this.update({ busy: true, error: '', notice: '' });
    try {
      // Stop uses the last session immediately; it must not wait behind a status request.
      const snapshot = urgent ? this.state.snapshot : await this.readStatus();
      if (!urgent && generation !== this.generation) throw new Error('Canceled by Stop or a new session');
      const envelope: CommandEnvelope | null = snapshot ? {
        schema_version: 1, session_id: snapshot.session_id,
        command_id: crypto.randomUUID(), command_epoch: snapshot.command_epoch,
        issued_at: Date.now() / 1000, expected_frame_id: snapshot.frame.id, name, payload,
      } : null;
      if (!envelope && !urgent) throw new Error('Connect to the engine first');
      const response = await this.fetcher(envelope ? '/api/v1/command' : `/api/${name}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Token': this.token },
        body: JSON.stringify(envelope ?? payload), signal: AbortSignal.timeout(12000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? `Command failed (${response.status})`);
      if (!urgent && generation !== this.generation) throw new Error('Canceled by Stop or a new session');
      return result as T;
    } finally {
      if (generation === this.generation) this.update({ busy: false });
    }
  }

  async restart(): Promise<void> {
    const result = await this.command<{ instance_id: string }>('restart_bot');
    this.update({ process: 'restarting', notice: 'Restarting unarmed. Waiting for the new engine…' });
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 350));
      try {
        const status = await this.readStatus();
        if (status.instance_id !== result.instance_id) { this.reload(); return; }
      } catch { /* The old process releases its port before the replacement starts. */ }
    }
    this.update({ process: 'running', connected: false });
    void this.poll();
    throw new Error('Restart did not finish within 20 seconds. Reload or use run.ps1.');
  }

  async shutdown(): Promise<void> {
    await this.command('shutdown_bot');
    this.update({ process: 'stopping', notice: 'Shutdown requested. Gameplay keys released.' });
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 350));
      try {
        await this.readStatus();
      } catch (error) {
        if (error instanceof DOMException && error.name === 'TimeoutError') continue;
        this.update({ process: 'stopped', connected: false, notice: 'Server stopped. Use run.ps1 to reopen it.' });
        return;
      }
    }
    this.update({ process: 'running' });
    void this.poll();
    throw new Error('The server has not finished stopping. Check its PowerShell window.');
  }
}

export function resultMessage(value: unknown): string {
  if (value && typeof value === 'object') {
    const result = value as Record<string, unknown>;
    if (result.receipt && typeof result.receipt === 'object' && 'revision' in result.receipt) return `Map saved · revision ${result.receipt.revision}. Gameplay stays stopped.`;
    if (typeof result.instruction === 'string') return result.instruction;
    if (typeof result.reason === 'string') return result.reason;
    if (typeof result.path === 'string') return `Saved: ${result.path}`;
    if (typeof result.mode === 'string') return `Mode: ${result.mode.replaceAll('_', ' ')}`;
    if (typeof result.variants === 'number') return `Loaded ${result.variants} template variants.`;
  }
  return 'Done.';
}
