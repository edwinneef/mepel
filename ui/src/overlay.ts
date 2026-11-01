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
  protected override pollInterval = 100;
  select: (action: OverlayAction) => void = () => {};
  selectionMessage = 'Selected. Close settings, focus the game and press F6 to turn On.';
  override async command<T = unknown>(name: string, payload: Record<string, unknown> = {}): Promise<T> {
    if (actions[name]) {
      this.select({ name, payload, label: name === 'probe' ? `Test ${payload.action}` : actions[name] });
      this.message(this.selectionMessage);
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
/** Passive walk-calibration progress for the game overlay, or null when nothing is learning. */
export function positionLearning(position: Snapshot['position'], now: number): string | null {
  const calibration = position?.calibration;
  if (!calibration) return null;
  const passive = calibration.passive;
  if (!calibration.saved && !calibration.active && passive && passive.reason !== 'Off') {
    return `Learning position · ${passive.reason}`;
  }
  if (calibration.saved && now - calibration.saved.captured_at * 1000 <= 10_000) {
    return `Position learned · ${calibration.saved.pairs} pairs`;
  }
  return null;
}

export function freshDetections(s: Pick<Snapshot, 'frame'> | null | undefined, connected: boolean, now: number): boolean {
  return Boolean(connected && s?.frame.available && s.frame.captured_at != null
    && now - s.frame.captured_at * 1000 >= 0 && now - s.frame.captured_at * 1000 <= 1500);
}
