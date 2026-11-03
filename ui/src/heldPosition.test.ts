import { describe, expect, it } from 'vitest';
import { estimatedPosition } from './heldPosition';
import type { LivePosition } from './contracts';

const position: LivePosition = {
  kind: 'platform', surface_id: 'floor', feet: [20, 30], reason: '', input_sent: false,
  estimate: { feet: [18, 30], confidence: 1, captured_at: 100,
    fresh: true, held: false, consecutive: 3, required: 3 },
};
const current = { feet: position.feet!, surface: 'floor', held: false };

describe('temporal position display', () => {
  it('uses the smoothed point without mutating movement coordinates', () => {
    expect(estimatedPosition(position, current, 100100).feet).toEqual([18, 30]);
    expect(position.feet).toEqual([20, 30]);
  });
  it('marks an old sample held without claiming a current surface', () => {
    expect(estimatedPosition(position, current, 100600)).toMatchObject({
      feet: [18, 30], surface: null, held: true,
    });
  });
  it('expires even if the same snapshot is repeatedly received', () => {
    expect(estimatedPosition(position, current, 101001).feet).toBeNull();
    expect(estimatedPosition(position, current, 99000).feet).toBeNull();
  });
  it('never presents a dropout or warmup as fresh', () => {
    const dropped = { ...position, estimate: { ...position.estimate!, fresh: false, held: true } };
    expect(estimatedPosition(dropped, current, 100100).held).toBe(true);
    const warming = { ...position, estimate: { ...position.estimate!, feet: null, fresh: false } };
    expect(estimatedPosition(warming, current, 100100).feet).toBeNull();
  });
});
