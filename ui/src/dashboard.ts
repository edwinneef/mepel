import type { OverlayClient, OverlayEvent } from './overlay';

// The server owns the deadline. A page timer can renew a lease, never authorize input.
export class DashboardSession {
  private readonly owner = crypto.randomUUID();
  private panel = true;
  private desiredPanel = true;
  private closed = false;
  private denied = false;
  private denialReason = '';
  private pending: Promise<void> = Promise.resolve();
  private renewing = false;
  private listeners = new Set<(event: OverlayEvent) => void>();

  constructor(private readonly token: string, private readonly fetcher: typeof fetch = globalThis.fetch.bind(globalThis)) {}

  get disconnected() { return this.closed || this.denied; }
  get connectionIssue() {
    return this.denialReason || 'The dashboard control connection ended. The game picture can still update while controls are disconnected.';
  }

  subscribe = (listener: (event: OverlayEvent) => void) => {
    this.listeners.add(listener);
    listener({ type: 'panel', value: this.panel });
    return () => { this.listeners.delete(listener); };
  };
  private emit(event: OverlayEvent) { this.listeners.forEach(listener => listener(event)); }

  private renew(panel: boolean): Promise<void> {
    const request = this.pending.catch(() => {}).then(async () => {
      if (this.closed || this.denied) throw new Error('Dashboard disconnected. Reload to reconnect.');
      const response = await this.fetcher('/api/dashboard', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Debug-Token': this.token },
        body: JSON.stringify({ owner: this.owner, panel }), signal: AbortSignal.timeout(1000),
      });
      const result = await response.json();
      if (!response.ok) {
        this.denied = response.status >= 400 && response.status < 500;
        if (this.denied) this.denialReason = result.error ?? 'Dashboard control connection refused';
        throw new Error(result.error ?? 'Dashboard lease unavailable');
      }
      if (this.closed) return;
      this.panel = panel;
      this.emit({ type: 'panel', value: panel });
      if (result.batch) this.emit({ type: 'batch', value: result.batch });
    });
    this.pending = request;
    return request;
  }

  settings = (open: boolean) => { this.desiredPanel = open; return this.renew(open); };
  /** Queue a guarded batch for the in-game overlay to run. The engine only stores the request. */
  startBatch = async (request: Record<string, unknown>) => {
    if (this.closed || this.denied) throw new Error('Dashboard disconnected. Reload to reconnect.');
    const response = await this.fetcher('/api/dashboard_batch', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Debug-Token': this.token },
      body: JSON.stringify({ ...request, owner: this.owner }), signal: AbortSignal.timeout(1500),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error ?? 'The batch was not queued');
    this.emit({ type: 'batch', value: { running: false, pending: true } });
    return result;
  };
  heartbeat = () => {
    if (this.closed || this.denied || this.renewing) return;
    this.renewing = true;
    void this.renew(this.desiredPanel).catch(error => this.emit({ type: 'error', value: error }))
      .finally(() => { this.renewing = false; });
  };
  quit = async () => { this.disconnect(); this.emit({ type: 'off' }); };

  disconnect = () => {
    if (this.closed) return;
    this.closed = true;
    // keepalive helps on page exit; server-side expiry covers crashes and lost networks.
    void this.fetcher('/api/dashboard_disconnect', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Debug-Token': this.token },
      body: JSON.stringify({ owner: this.owner }), keepalive: true,
    }).catch(() => {});
  };

  connect(client: OverlayClient): () => void {
    client.selectionMessage = 'Selected. Click Start on Run, then focus the game during the countdown.';
    let connected = false;
    const unsubscribe = client.subscribe(() => {
      const state = client.getState();
      if (state.connected) connected = true;
      if (connected && (!state.connected || state.needsReload)) this.disconnect();
    });
    window.addEventListener('pagehide', this.disconnect);
    window.addEventListener('offline', this.disconnect);
    return () => {
      unsubscribe();
      window.removeEventListener('pagehide', this.disconnect);
      window.removeEventListener('offline', this.disconnect);
      this.disconnect();
    };
  }
}
