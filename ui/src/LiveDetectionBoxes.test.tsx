import { expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { EnemyTrackDiagnostics, predictBoxes, projectDisplayBoxes } from './LiveDetectionBoxes';
import type { Detection } from './contracts';

const monster = (x: number, template = 'catalog:Pig:stand-0'): Detection => ({
  kind: 'monster', template, confidence: 1, tracked: false,
  box: { x, y: 100, width: 40, height: 40 },
});

it('draws uncertain enemy estimates separately from visible sprite bounds', () => {
  const { container, getByText } = render(<svg><EnemyTrackDiagnostics tracks={[{
    track_id: 'enemy:7', enemy_type: 'catalog:Snail', state: 'occluded',
    predicted_position: [120, 140], ground_position: [120, 140], visible_bounds: null,
    confidence: .6, uncertainty: [40, 8], last_seen: 1, observed: false,
  }]} /></svg>);
  expect(getByText(/enemy:7.*occluded.*60%.*prediction only/)).toBeTruthy();
  expect(container.querySelector('ellipse')?.getAttribute('rx')).toBe('40');
  expect(container.querySelector('rect')).toBeNull();
});

it('compensates capture delay across animation frames without mutating engine observations', () => {
  const current = monster(130, 'catalog:Pig:move-1');
  const predicted = predictBoxes([current], [monster(100)], .3, 200);
  expect(predicted[0].box.x).toBe(150);
  expect(current.box.x).toBe(130);
  expect(predictBoxes([current], [monster(100)], .3, 500)[0].box.x).toBe(155);
});

it('does not predict across species, ambiguous crossings, long gaps or stale frames', () => {
  const current = monster(130);
  expect(predictBoxes([current], [monster(100, 'catalog:Slime:move-1')], .3, 200)[0]).toBe(current);
  expect(predictBoxes([current], [monster(100), monster(150)], .3, 200)[0]).toBe(current);
  expect(predictBoxes([current, monster(135)], [monster(100)], .3, 200)[0]).toBe(current);
  expect(predictBoxes([current], [monster(100)], 1, 200)[0]).toBe(current);
  expect(predictBoxes([current], [monster(100)], .3, 800)[0]).toBe(current);
});

it('bridges fast packets using stable IDs and caps transport compensation', () => {
  const previous = { ...monster(100), track_id: 'pig:1', tracked: true };
  const current = { ...monster(104), track_id: 'pig:1', tracked: true };
  expect(projectDisplayBoxes([current], [previous], .04, 20)[0].box.x).toBe(106);
  expect(projectDisplayBoxes([current], [previous], .04, 200)[0].box.x).toBe(109);
  expect(current.box.x).toBe(104);
  expect(projectDisplayBoxes([current], [{ ...previous, track_id: 'pig:2' }], .04, 20)[0]).toBe(current);
});

it('does not extrapolate recognition corrections, missing tracks or long gaps', () => {
  const current = { ...monster(150), track_id: 'pig:1' };
  const previous = { ...monster(100), track_id: 'pig:1' };
  expect(projectDisplayBoxes([current], [previous], .04, 20)[0]).toBe(current);
  expect(projectDisplayBoxes([current], [{ ...previous, box: { ...previous.box, x: 145 } }], .3, 20)[0]).toBe(current);
  expect(projectDisplayBoxes([monster(104)], [monster(100)], .04, 20)[0].box.x).toBe(104);
});
