import { useEffect, useState } from 'react';
import type { Snapshot } from './contracts';
import type { EngineClient } from './client';
import { KeyCap, displayKey } from './ClearParts';

/* Set up › Keys (design 2a). The engine validates and saves to config.toml; keys apply at the next
   engine restart, and every start is refused until then. Potion keys are confirmed afterwards with
   the existing guarded control test. */

export type KeySettingsState = NonNullable<Snapshot['key_settings']>;

const GAME: { id: string; label: string; used: string; probe?: string; uncheckable?: boolean }[] = [
  { id: 'hp_potion', label: 'HP potion', used: 'When HP drops under its line.', probe: 'hp_potion' },
  { id: 'mp_potion', label: 'MP potion', used: 'When MP drops under its line.', probe: 'mp_potion' },
  { id: 'pet_food', label: 'Pet food', used: 'On a timer, so pet loot keeps working.', uncheckable: true },
  { id: 'attack', label: 'Attack', used: 'Basic attack.', probe: 'attack' },
  { id: 'skill', label: 'Attack skill', used: 'Used while MP is high enough.', probe: 'skill' },
  { id: 'jump', label: 'Jump', used: 'Moving between platforms.', probe: 'jump' },
];
const BOT: { id: string; label: string; used: string }[] = [
  { id: 'start_stop', label: 'Start or stop', used: 'While the game or dashboard is in front.' },
  { id: 'emergency_key', label: 'Stop from anywhere', used: 'Always stops and releases every key.' },
  { id: 'drawings', label: 'Show or hide drawings', used: 'Enemy boxes on the game.' },
];
const FEED = [300, 600, 900];

/** config.toml key name for a pressed key, or null when the bot cannot press it. */
export function configKey(event: Pick<KeyboardEvent, 'key'>): string | null {
  const key = event.key;
  if (key === 'Control') return 'ctrl';
  if (key === 'Alt') return 'alt';
  if (key === ' ') return 'space';
  if (/^F([1-9]|1[0-2])$/.test(key)) return key.toLowerCase();
  if (['Insert', 'Delete', 'Home', 'End', 'PageUp', 'PageDown'].includes(key)) return key.toLowerCase();
  if (/^[a-z0-9]$/i.test(key)) return key.toLowerCase();
  return null;
}

export function KeySettings({ snapshot: s, client, disabled, onTest }: {
  snapshot: Snapshot; client: EngineClient; disabled: boolean; onTest(): void;
}) {
  const settings = s.key_settings;
  const saved = settings?.saved;
  const [draft, setDraft] = useState<Record<string, string | number>>({});
  const [capturing, setCapturing] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const value = (id: string) => (id in draft ? draft[id] : saved?.[id]) as string | undefined;
  useEffect(() => {
    if (!capturing) return;
    // Capture phase on window: the dashboard's own F-key shortcuts never see a key being bound.
    const keydown = (event: KeyboardEvent) => {
      event.preventDefault(); event.stopPropagation();
      if (event.key === 'Escape') { setCapturing(null); setMessage('Nothing changed.'); return; }
      if (event.key.startsWith('Arrow')) { setMessage('Arrow keys move the character and cannot be used here.'); return; }
      const key = configKey(event);
      if (!key || !settings?.supported.includes(key)) {
        setMessage(`${event.key} can't be pressed by the bot. Try a letter, number, F-key, Ctrl, Alt, Space or Insert to Page Down.`);
        return;
      }
      setDraft(current => ({ ...current, [capturing]: key }));
      setMessage(`${displayKey(key)} chosen. Save keys to keep it.`);
      setCapturing(null);
    };
    window.addEventListener('keydown', keydown, true);
    return () => window.removeEventListener('keydown', keydown, true);
  }, [capturing, settings?.supported]);
  if (!settings || !saved) return <p className="c-quiet">This engine does not report its keys yet. Update the engine to change keys here.</p>;
  const changes = Object.fromEntries(Object.entries(draft).filter(([id, v]) => saved[id] !== v));
  const dirty = Object.keys(changes).length > 0;
  const locked = disabled || !settings.editable;
  const save = async () => {
    setSaving(true);
    try {
      await client.command('input_keys_set', { keys: changes });
      setDraft({});
      setMessage('Saved to config.toml. Restart the engine to use the new keys.');
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setSaving(false); }
  };
  const status = (row: typeof GAME[number]) => {
    if (row.id in changes) return <span className="ks wait">Not saved yet</span>;
    if (settings.restart_required && saved[row.id] !== settings.active[row.id]) return <span className="ks warn">Applies after restart</span>;
    if (row.uncheckable) return <span className="ks muted">Can't be checked automatically. Watch the pet eat.</span>;
    const confirmed = row.probe ? s.probes[row.probe]?.confirmed : undefined;
    if (confirmed) return <span className="ks ok">Works</span>;
    return <><span className="ks warn">Not tested</span> <button className="c-btn small" disabled={disabled} onClick={onTest}>Go to the control tests</button></>;
  };
  const table = (rows: { id: string; label: string; used: string }[], game: boolean) => <table className="c-keytable">
    <thead><tr><th scope="col">Action</th><th scope="col">Key</th><th scope="col">{game ? 'Works?' : ''}</th></tr></thead>
    <tbody>{rows.map(row => <tr key={row.id} data-changed={row.id in changes || undefined}>
      <th scope="row"><b>{row.label}</b><span>{row.used}</span></th>
      <td><KeyCap label={row.label} value={value(row.id) ?? null} capturing={capturing === row.id} disabled={locked}
        onClick={() => { setCapturing(current => current === row.id ? null : row.id); setMessage(`Press the key for ${row.label}. Esc cancels.`); }} /></td>
      <td>{game ? status(row as typeof GAME[number]) : row.id in changes ? <span className="ks wait">Not saved yet</span>
        : settings.restart_required && saved[row.id] !== settings.active[row.id] ? <span className="ks warn">Applies after restart</span> : <span className="ks ok">Set</span>}</td>
    </tr>)}</tbody></table>;
  const feed = Number(value('pet_feed_seconds') ?? 600);
  return <div className="c-keys">
    {settings.restart_required && <p className="c-banner warn">New keys are saved. Restart the engine to use them; until then every start is refused.
      Run <code>.\restart.ps1</code> in the project root, then test the changed potion keys.</p>}
    {!settings.editable && <p className="c-quiet">This engine session was started without a config file, so keys are read-only.</p>}
    <section className="c-card"><h2>Keys in the game</h2>
      <p className="c-quiet">Use the same keys as your in-game key setup. Arrow keys always move the character.</p>
      {table(GAME, true)}</section>
    <section className="c-card"><h2>Bot hotkeys</h2>
      <p className="c-quiet">F1 to F12 only. The stop key always works, even while the bot holds keys.</p>
      {table(BOT, false)}</section>
    <section className="c-card"><h2>Pet food</h2>
      <div className="c-field"><span>Feed the pet every</span>
        <div className="c-seg" role="radiogroup" aria-label="Feed the pet every">{FEED.map(seconds =>
          <button key={seconds} className="c-opt" role="radio" aria-checked={feed === seconds} disabled={locked}
            onClick={() => setDraft(current => ({ ...current, pet_feed_seconds: seconds }))}>{seconds / 60} min</button>)}</div></div></section>
    <div className="c-keys-save">
      <p className="c-keymsg" role="status">{message || 'Click a key to change it, then press the new key.'}</p>
      <button className="c-btn" disabled={!dirty || saving} onClick={() => { setDraft({}); setMessage('Changes discarded.'); }}>Discard</button>
      <button className="c-btn start" disabled={!dirty || saving || locked} onClick={() => void save()}>Save keys</button>
    </div>
  </div>;
}
