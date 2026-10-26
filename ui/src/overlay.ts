import { EngineClient } from './client';
import type { Snapshot } from './contracts';

export interface OverlayAction { name: string; payload: Record<string, unknown>; label: string }
export interface OverlayEvent { type: string; value?: unknown }
declare global {
  interface Window {
    mapleOverlay?: {
      settings(open: boolean): Promise<void>; quit(): Promise<void>; heartbeat(): void;
      subscribe(callback: (event: OverlayEvent) => void): () => void;
    };
  }
}
export const actions: Record<string, string> = {
  arm: 'Combat', dry_run: 'Decision preview', nav_go: 'Navigation', nav_start: 'Navigation',
  autopotter_live: 'Live potions', autopotter_start: 'Potion preview', probe: 'Control probe',
};
export class OverlayClient extends EngineClient {
  select: (action: OverlayAction) => void = () => {};
  override async command<T = unknown>(name: string, payload: Record<string, unknown> = {}): Promise<T> {
    if (actions[name]) {
      this.select({ name, payload, label: name === 'probe' ? `Test ${payload.action}` : actions[name] });
      this.message('Selected. Close settings, focus the game and press F6 to turn On.');
      return undefined as T;
    }
    return super.command<T>(name, payload);
  }
  execute(action: OverlayAction): Promise<unknown> { return super.command(action.name, action.payload); }
}
export function isRunning(s: Snapshot | null): boolean {
  return Boolean(s && !s.alarm.active && (s.navigation?.active
    || (s.mode !== 'capture' && s.mode !== 'probe_confirm')
    || s.autopotter.enabled));
}
export function freshDetections(s: Snapshot | null, connected: boolean, now: number): boolean {
  return Boolean(connected && s?.frame.available && s.frame.captured_at != null
    && now - s.frame.captured_at * 1000 >= 0 && now - s.frame.captured_at * 1000 <= 1500);
}
