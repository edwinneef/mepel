import type { Rect } from './contracts';

export interface Point { x: number; y: number }

export function nativePoint(
  point: Point, bounds: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>,
  width: number, height: number,
): Point {
  return {
    x: Math.max(0, Math.min(width, Math.round((point.x - bounds.left) * width / bounds.width))),
    y: Math.max(0, Math.min(height, Math.round((point.y - bounds.top) * height / bounds.height))),
  };
}

export function rectangle(a: Point, b: Point): Rect {
  return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) };
}
