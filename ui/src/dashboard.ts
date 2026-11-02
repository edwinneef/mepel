import type { OverlayClient, OverlayEvent } from './overlay';

const STATUS_GRACE_MS = 1500;

// The server owns the deadline. A page timer can renew a lease, never authorize input.
export class DashboardSession {
  private readonly owner = crypto.randomUUID();
  private panel = true;
  private desiredPanel = true;
  private closed = false;
  private denied = false;
  private denialReason = '';
  private closeReason = '';
  private pending: Promise<void> = Promise.resolve();
  private renewing = false;
  private listeners = new Set<(event: OverlayEvent) => void>();
  // Drawing toggles, sent with each heartbeat so the in-game overlay shows the same layers.
  private display: Record<'enemies' | 'range' | 'lines', boolean> | null = null;

  constructor(private readonly token: string, private readonly fetcher: typeof fetch = globalThis.fetch.bind(globalThis)) {}

  get disconnected() { return this.closed || this.denied; }
  get connectionIssue() {
    return this.denialReason || `The dashboard control connection ended${this.closeReason ? `: ${this.closeReason}` : ''}. The game picture can still update while controls are disconnected.`;
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
        body: JSON.stringify({ owner: this.owner, panel, ...(this.display ? { display: this.display } : {}) }),
        signal: AbortSignal.timeout(1000),
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
  setDisplay = (display: Record<'enemies' | 'range' | 'lines', boolean>) => { this.display = display; };
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

  disconnect = (reason: unknown = 'page unloaded or dashboard closed') => {
    if (this.closed) return;
    this.closed = true;
    this.closeReason = typeof reason === 'string' ? reason : 'page hidden or closed';
    // keepalive helps on page exit; server-side expiry covers crashes and lost networks.
    void this.fetcher('/api/dashboard_disconnect', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Debug-Token': this.token },
      body: JSON.stringify({ owner: this.owner }), keepalive: true,
    }).catch(() => {});
  };

  connect(client: OverlayClient): () => void {
    client.selectionMessage = 'Selected. Click Start on Run, then focus the game during the countdown.';
    let connected = false;
    let lostTimer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = client.subscribe(() => {
      const state = client.getState();
      if (state.connected) { connected = true; clearTimeout(lostTimer); lostTimer = undefined; }
      if (connected && state.needsReload) this.disconnect('the engine started a new session');
      // One slow or dropped status poll (the batch start loads the engine and the browser loses focus)
      // must not end the lease. The server expires it after 2 s without heartbeats and stops input.
      else if (connected && !state.connected && lostTimer === undefined) {
        lostTimer = setTimeout(() => {
          const now = client.getState();
          if (!now.connected) this.disconnect(`engine status stopped answering (${now.error || 'no reason given'})`);
        }, STATUS_GRACE_MS);
      }
    });
    const onPageHide = () => this.disconnect('the page was hidden or closed');
    const onOffline = () => this.disconnect('the browser went offline');
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('offline', onOffline);
    return () => {
      unsubscribe();
      clearTimeout(lostTimer);
      window.removeEventListener('pagehide', onPageHide);
      window.removeEventListener('offline', onOffline);
      this.disconnect('the dashboard was closed or reloaded');
    };
  }
}
