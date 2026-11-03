import { useEffect, useRef, useState } from 'react';
import type { Snapshot } from './contracts';

// The engine marks a reading stale after 0.5 s; at low capture rates that is every other
// update. Displays keep the last fresh reading this long (marked held) instead of blinking.
// Display only: safety checks keep reading the engine's own stale flag.
export const HOLD_MS = 2000;

export interface HeldPosition {
  area?: string; surface: string | null; kind?: string; feet: [number, number] | null;
  /** True while showing the previous fresh reading through a brief gap. */
  held: boolean;
}

export function useHeldPosition(position: Snapshot['position'] | undefined): HeldPosition {
  const estimate = position?.estimate;
  const fresh = Boolean(position?.feet && !position.stale && (!estimate || estimate.fresh));
  const last = useRef<{ value: HeldPosition; at: number } | null>(null);
  const [, tick] = useState(0);
  const current: HeldPosition = {
    area: position?.area_id, kind: position?.kind,
    feet: estimate ? estimate.feet : position?.feet ?? null,
    surface: position?.kind === 'platform' || position?.kind === 'rope' ? position.surface_id ?? null : null,
    held: false,
  };
  if (fresh) last.current = { value: current, at: Date.now() };
  useEffect(() => {
    if (estimate) {
      const timer = setInterval(() => tick(n => n + 1), 100);
      return () => clearInterval(timer);
    }
    if (fresh) return;
    const timer = setTimeout(() => tick(n => n + 1), HOLD_MS);
    return () => clearTimeout(timer);
  }, [fresh, Boolean(estimate)]);
  const previous = last.current;
  if (estimate) return estimatedPosition(position, current, Date.now());
  if (!fresh && previous && previous.value.area === position?.area_id && Date.now() - previous.at < HOLD_MS) {
    return { ...previous.value, held: true };
  }
  return current;
}

export function estimatedPosition(position: Snapshot['position'] | undefined,
  current: HeldPosition, now: number): HeldPosition {
  const estimate = position?.estimate;
  const age = estimate?.captured_at == null ? Infinity : now - estimate.captured_at * 1000;
  if (!estimate || !Number.isFinite(age) || age < 0 || age >= 1000 || !estimate.feet) {
    return { ...current, feet: null, surface: null, held: false };
  }
  const held = !estimate.fresh || Boolean(position?.stale) || age > 500;
  return { ...current, feet: estimate.feet, surface: held ? null : current.surface, held };
}
