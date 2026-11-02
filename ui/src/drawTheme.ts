/* Design 2a colours for drawings on the game picture (dashboard view and the native overlay).
   Plain labels with a dark halo stay readable over bright MapleStory scenery. */
export const DRAW = {
  player: '#3ddc84',
  enemy: '#ffb020',
  target: '#ff5c7a',
  range: '#4da3ff',
  /** Below the minimum attack distance. */
  tooClose: '#ffb967',
  line: '#ffffff',
  current: '#3ddc84',
  provisional: '#ffd07a',
  /** Tracking diagnostics that are not live detections. */
  diagnostic: '#aab9ca',
  search: '#8aa0b4',
  note: '#d9e6f2',
  halo: '#12263a',
  font: "'Atkinson Hyperlegible', 'Segoe UI', system-ui, sans-serif",
} as const;

/** SVG text props for a label with a halo. */
export const label = (color: string) => ({
  fill: color, stroke: DRAW.halo, strokeWidth: 3, paintOrder: 'stroke' as const, fontFamily: DRAW.font, fontWeight: 700,
});
