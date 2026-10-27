import type { ToolProps } from './tools';
import { Controls } from './tools';

export function BowmanSetup({ onSetup, ...props }: ToolProps & { onSetup: (tab: string) => void }) {
  const s = props.snapshot;
  const range = s.attack_setup;
  return <section aria-label="Bowman setup">
    <h2>Bowman on one platform</h2>
    <p>Verify attacks, measure their shared reach, then preview before combat.</p>
    <dl>
      <div><dt>Game picture</dt><dd>{s.readiness.preview.reason}</dd></div>
      <div><dt>Combat</dt><dd>{s.readiness.combat.reason}</dd></div>
      <div><dt>Potions</dt><dd>{s.readiness.potions.reason}</dd></div>
    </dl>
    <div className="button-grid">
      <button onClick={() => onSetup('Recognition')}>Player and enemy setup</button>
      <button onClick={() => onSetup('Potions')}>Potion setup</button>
    </div>
    <Controls {...props} bowman />
    <section className="tool-group" aria-label="Attack setup">
      <h3>Measure attack reach</h3>
      <p>Basic attack: {s.bindings.attack ?? '—'} · Skill: {s.bindings.skill ?? '—'}</p>
      <p>{range ? `Engine-loaded range: ${range.minimum_px}–${range.maximum_px} px` : 'Engine-loaded range unavailable; update the engine.'}</p>
      <strong>{range?.measured ? 'Measured shared range' : 'Hit range not yet verified'}</strong>
      <p>Use visible damage on the same-platform enemy for both attacks. A key press or projectile alone does not prove a hit. Do not start combat with unmeasured tuning.</p>
      <p>Below minimum reach the bot stops for manual repositioning. No retreat or platform crossing.</p>
    </section>
  </section>;
}
