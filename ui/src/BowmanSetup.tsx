import { useEffect, useState } from 'react';
import type { Snapshot } from './contracts';
import type { ToolProps } from './tools';
import { Controls } from './tools';

type RangeSetup = NonNullable<Snapshot['attack_setup']> & {
  profile?: string;
  profiles?: { id: string; label: string; minimum_px: number; maximum_px: number }[];
};

export function BowmanSetup({ onSetup, ...props }: ToolProps & { onSetup: (tab: string) => void }) {
  const s = props.snapshot;
  const range = s.attack_setup as RangeSetup | undefined;
  const [profile, setProfile] = useState(range?.profile ?? 'custom');
  useEffect(() => setProfile(range?.profile ?? 'custom'), [range?.profile]);
  return <section aria-label="Combat setup">
    <h2>Combat on one platform</h2>
    <p>Choose your weapon range, then preview before combat.</p>
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
      <h3>Weapon range</h3>
      {range?.profiles && <>
        <label>Classic weapon<select value={profile} disabled={props.disabled || Boolean(s.active_probe)}
          onChange={event => setProfile(event.target.value)}>
          <option value="custom">Custom · startup band</option>
          {range.profiles.map(item => <option key={item.id} value={item.id}>
            {item.label} · {item.minimum_px}–{item.maximum_px} px
          </option>)}
        </select></label>
        <button disabled={props.disabled || Boolean(s.active_probe) || profile === range.profile}
          onClick={() => void props.act(() => props.client.command('range_profile', { profile }))}>
          Apply weapon range
        </button>
        <p>Applying stops the bot and saves this choice. Select your equipped weapon; equipment is not detected automatically.</p>
      </>}
      <p>Basic attack: {s.bindings.attack ?? '—'} · Skill: {s.bindings.skill ?? '—'}</p>
      <p>{range ? `Engine-loaded range: ${range.minimum_px}–${range.maximum_px} px` : 'Engine-loaded range unavailable; update the engine.'}</p>
      <strong>{range?.measured ? 'Measured shared range' : range?.profile && range.profile !== 'custom'
        ? 'Classic baseline · conservative operating band' : 'Hit range not yet verified'}</strong>
      <p>Both attacks share this band, including basic attack when MP is low. Presets use margins inside Classic reach; exact hit limits remain unmeasured.</p>
      <details><summary>Warrior weapon exceptions</summary>
        <p>Short 1H group: Long Sword, Beginner's Long Sword, Gladius, Old Gladius, Hero's Gladius, Traus, Jeweled Katar, Sky Blue Umbrella and Yellow Umbrella.</p>
        <p>Long 2H group: Scimitar, Lion's Fang, Sparta and Doombringer. Other swords use the standard group.</p>
        <p>Warrior presets cover normal attacks and Power Strike. Slash Blast still needs a target inside weapon reach; its wider follow-up area does not extend approach distance.</p>
      </details>
      <p>Below minimum reach the bot stops for manual repositioning. No retreat or platform crossing.</p>
    </section>
  </section>;
}
