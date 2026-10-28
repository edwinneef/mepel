import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { SavedTerrainOverlay } from './SavedTerrainOverlay';
import type { AreaProfile, LivePosition } from './contracts';

afterEach(cleanup);
const map: AreaProfile = { schema_version: 2, id: 'map', revision: 3, name: 'Map',
  boundary: { x: 0, y: 0, width: 1000, height: 1000 }, views: [], zones: [], links: [],
  platforms: [{ id: 'floor', start: { x: 100, y: 200 }, end: { x: 300, y: 210 } }],
  ropes: [{ id: 'rope', start: { x: 200, y: 50 }, end: { x: 200, y: 200 } }],
};
const position: LivePosition = { area_id: 'map', kind: 'platform', surface_id: 'floor',
  reason: 'Matched', input_sent: false, captured_at: 10,
  projection: { x: -30, y: 50, scale: 2, revision: 3 } };

it('projects slopes and ropes with scale and camera translation, separately labelled', () => {
  const view = render(<svg><SavedTerrainOverlay map={map} position={position} now={10100} /></svg>);
  const lines = view.container.querySelectorAll('line');
  expect(lines).toHaveLength(2);
  expect(lines[0].getAttribute('x1')).toBe('170');
  expect(lines[0].getAttribute('y2')).toBe('470');
  expect(lines[1].getAttribute('x1')).toBe('370');
  expect(screen.getByText('Saved · floor · spatial match')).toBeTruthy();
  expect(screen.getByText(/not live detection/)).toBeTruthy();
});

it('labels provisional coverage separately and hides it on disable or stale observations', () => {
  const provisional: LivePosition = { ...position, provisional: true, surface_id: 'extra',
    supplement: { available: true, enabled: true, reason: 'Observation only',
      platform: { id: 'extra', start: { x: 150, y: 200 }, end: { x: 200, y: 200 } } } };
  const { rerender } = render(<svg><SavedTerrainOverlay map={map} position={provisional} now={10100} /></svg>);
  expect(screen.getByText('Provisional · middle ledge · observation only')).toBeTruthy();
  expect(map.platforms).toHaveLength(1);
  rerender(<svg><SavedTerrainOverlay map={map} position={{ ...provisional,
    supplement: { ...provisional.supplement!, enabled: false } }} now={10100} /></svg>);
  expect(screen.queryByLabelText('Provisional middle ledge')).toBeNull();
  rerender(<svg><SavedTerrainOverlay map={map} position={provisional} now={11000} /></svg>);
  expect(screen.queryByLabelText('Provisional middle ledge')).toBeNull();
});

it.each([
  { stale: true }, { kind: 'unknown' }, { area_id: 'other' }, { captured_at: 9 },
  { captured_at: 11 }, { captured_at: undefined }, { projection: null },
  { projection: { ...position.projection!, revision: 2 } },
  { projection: { ...position.projection!, scale: NaN } },
])('hides uncertain, old or mismatched alignment: %j', change => {
  const view = render(<svg><SavedTerrainOverlay map={map} position={{ ...position, ...change }} now={10100} /></svg>);
  expect(view.container.querySelector('g')).toBeNull();
});

it('bridges a short localization gap without claiming a current spatial match, then expires', () => {
  const view = render(<svg><SavedTerrainOverlay map={map} position={position} now={10100} /></svg>);
  const lost = { ...position, kind: 'unknown', projection: null, stale: true };
  view.rerender(<svg><SavedTerrainOverlay map={map} position={lost} now={10600} /></svg>);
  expect(view.container.querySelectorAll('line')).toHaveLength(2);
  expect(screen.queryByText(/spatial match/)).toBeNull();
  expect(screen.getByText(/brief hold/)).toBeTruthy();
  view.rerender(<svg><SavedTerrainOverlay map={map} position={lost} now={10800} /></svg>);
  expect(view.container.querySelector('g')).toBeNull();
});

it('discards retained terrain when the map or capture position is cleared', () => {
  const view = render(<svg><SavedTerrainOverlay map={map} position={position} now={10100} /></svg>);
  view.rerender(<svg><SavedTerrainOverlay map={map} position={null} now={10200} /></svg>);
  expect(view.container.querySelector('g')).toBeNull();
  view.rerender(<svg><SavedTerrainOverlay map={{ ...map, revision: 4 }} position={position} now={10300} /></svg>);
  expect(view.container.querySelector('g')).toBeNull();
});

it('keeps freshly registered terrain without platform contact and clears on registration loss', () => {
  const alignment = { ...position, kind: 'unknown', surface_id: null, alignment: { valid: true } };
  const view = render(<svg><SavedTerrainOverlay map={map} position={null} alignment={alignment} now={10100} /></svg>);
  expect(view.container.querySelectorAll('line')).toHaveLength(2);
  expect(screen.queryByText(/spatial match/)).toBeNull();
  view.rerender(<svg><SavedTerrainOverlay map={map} position={position} alignment={null} now={10200} /></svg>);
  expect(view.container.querySelector('g')).toBeNull();
  view.rerender(<svg><SavedTerrainOverlay map={map} alignment={{ ...alignment, alignment: { valid: false } }} now={10200} /></svg>);
  expect(view.container.querySelector('g')).toBeNull();
  view.rerender(<svg><SavedTerrainOverlay map={map} alignment={alignment} now={10600} /></svg>);
  expect(view.container.querySelector('g')).toBeNull();
});
