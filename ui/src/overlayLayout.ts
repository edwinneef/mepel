import { useRef, useState } from 'react';
import type { PointerEvent } from 'react';

export interface PanelPoint { x: number; y: number }
export type PanelName = 'hud' | 'terrain' | 'settings';
type Positions = Partial<Record<PanelName, PanelPoint>>;
const storageKey = 'maple-overlay-panel-positions-v1';

export function keepHandleVisible(point: PanelPoint, width: number, height: number): PanelPoint {
  return { x: Math.round(Math.max(0, Math.min(point.x, Math.max(0, width - 120)))),
    y: Math.round(Math.max(0, Math.min(point.y, Math.max(0, height - 44)))) };
}
function readPositions(): Positions {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? '{}');
    return Object.fromEntries(['hud', 'terrain', 'settings'].flatMap(name => {
      const point = saved?.[name];
      return point && Number.isFinite(point.x) && Number.isFinite(point.y) ? [[name, point]] : [];
    }));
  } catch { return {}; }
}
export function useOverlayLayout(enabled: boolean) {
  const [positions, setPositions] = useState<Positions>(readPositions);
  const drag = useRef<{ name: PanelName; x: number; y: number; origin: PanelPoint } | null>(null);
  const save = (next: Positions) => {
    setPositions(next);
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Session-only layout. */ }
  };
  const handlers = (name: PanelName) => ({
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      if (!enabled || event.button !== 0 || (event.target as HTMLElement).closest('button, input, select')) return;
      const rect = event.currentTarget.parentElement!.getBoundingClientRect();
      drag.current = { name, x: event.clientX, y: event.clientY, origin: { x: rect.x, y: rect.y } };
      event.currentTarget.setPointerCapture(event.pointerId);
      event.preventDefault();
    },
    onPointerMove: (event: PointerEvent<HTMLElement>) => {
      const current = drag.current;
      if (!enabled || !current) return;
      const point = keepHandleVisible({ x: current.origin.x + event.clientX - current.x,
        y: current.origin.y + event.clientY - current.y }, innerWidth, innerHeight);
      setPositions(previous => ({ ...previous, [current.name]: point }));
    },
    onPointerUp: () => { if (drag.current) { drag.current = null; save(positions); } },
    onPointerCancel: () => { drag.current = null; },
  });
  const position = (name: PanelName, fallback: PanelPoint) => {
    const point = keepHandleVisible(positions[name] ?? fallback, innerWidth, innerHeight);
    return { left: point.x, top: point.y, right: 'auto', bottom: 'auto' };
  };
  return { handlers, position, reset: () => save({}) };
}
