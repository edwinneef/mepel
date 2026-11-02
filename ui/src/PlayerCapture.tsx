import './PlayerCapture.css';
import { useState } from 'react';
import type { Snapshot } from './contracts';
import type { EngineClient } from './client';

/** The operator's in-game name for a taught tag, or its position when none was entered.
 * Several tags can share one name (taught in different spots), so repeats show their id. */
export function tagName(identity: string, identities: string[], labels: Record<string, string> = {}) {
  const label = labels[identity];
  if (!label) return `Taught name ${identities.indexOf(identity) + 1}`;
  return identities.filter(other => labels[other] === label).length > 1 ? `${label} · ${identity.slice(0, 6)}` : label;
}

/** Taught tags grouped by in-game name: one entry per character, unnamed tags on their own. */
export function tagGroups(identities: string[], labels: Record<string, string> = {}) {
  const groups: { name: string; ids: string[] }[] = [];
  for (const identity of identities) {
    const label = labels[identity];
    const group = label ? groups.find(item => item.name === label) : undefined;
    if (group) group.ids.push(identity);
    else groups.push({ name: label || tagName(identity, identities), ids: [identity] });
  }
  return groups;
}

export function PlayerCapture({ snapshot, client, act, disabled }: {
  snapshot: Snapshot; client: EngineClient; disabled: boolean;
  act: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [checked, setChecked] = useState<string[]>([]);
  const poses = snapshot.pose_collection;
  const identities = poses?.identities ?? [];
  const labels = poses?.labels ?? {};
  const [identity, setIdentity] = useState('');
  const [rename, setRename] = useState<{ identity: string; value: string } | null>(null);
  const groups = tagGroups(identities, labels);
  // Default to the character recognition is following right now.
  const trackedId = snapshot.player_tracking?.identity?.startsWith('nametag:')
    ? snapshot.player_tracking.identity.slice('nametag:'.length) : '';
  const tracked = identities.includes(trackedId) ? trackedId : '';
  const selected = identities.includes(identity) ? identity : tracked
    || (identities.includes(poses?.identity ?? '') ? poses!.identity : groups.length === 1 ? identities[0] : '');
  const group = groups.find(item => item.ids.includes(selected));
  const available = (poses?.candidates ?? []).filter(candidate => !candidate.added);
  const chosen = checked.filter(id => available.some(candidate => candidate.id === id));
  const locked = disabled || busy || Boolean(poses?.enabled) || Boolean(poses?.pending);
  const run = async (payload: Record<string, unknown>) => {
    setBusy(true);
    try { await act(() => client.command('pose_collection', payload)); }
    finally { setBusy(false); }
  };
  return <div aria-label="Player screenshots">
    {groups.length > 1 && <div className="player-picker">
      <button type="button" className="player-picker-toggle" aria-expanded={choosing}
        disabled={disabled || busy || poses?.enabled} onClick={() => setChoosing(!choosing)}>
        <span>{group ? group.name : 'Select taught name'}</span><span aria-hidden="true">{choosing ? '^' : 'v'}</span>
      </button>
      {choosing && <div className="player-picker-options" role="group" aria-label="Taught names">
        {groups.map(item => <button key={item.ids[0]} type="button" title={item.ids.join(', ')}
          aria-pressed={group === item} disabled={disabled || busy || poses?.enabled}
          onClick={() => { setIdentity(item.ids.includes(tracked) ? tracked : item.ids[0]); setChoosing(false); }}>
          {item.name}{item.ids.includes(tracked) ? ' (playing)' : ''}{group === item ? ' (selected)' : ''}</button>)}
      </div>}
    </div>}
    {selected && <form className="player-name" onSubmit={event => {
      event.preventDefault();
      if (rename?.identity !== selected) return;
      // Every tag taught for this character carries the same name.
      const ids = group?.ids ?? [selected];
      void act(async () => { for (const id of ids) await client.command('nametag_label', { identity: id, label: rename.value }); })
        .then(() => setRename(null));
    }}>
      <label>In-game name<input aria-label="In-game name" maxLength={24} disabled={disabled}
        placeholder={tagName(selected, identities)} value={rename?.identity === selected ? rename.value : labels[selected] ?? ''}
        onChange={event => setRename({ identity: selected, value: event.target.value })} /></label>
      <button type="submit" disabled={disabled || rename?.identity !== selected}>Save name</button>
    </form>}
    <button disabled={disabled || busy || !poses || (!poses.enabled && (!selected || poses.pending > 0))}
      onClick={() => void run(poses?.enabled ? { enabled: false } : { enabled: true, identity: selected, outfit: `capture-${Date.now()}` })}>
      {poses?.enabled ? 'Cancel screenshot capture' : 'Capture player screenshots'}</button>
    <p aria-live="polite">{!identities.length ? 'Add a name tag in Tracking first.' : poses?.enabled ? `${poses.saved}/${poses.limit} saved  /  ${poses.reason}  /  stops after 30 seconds` : `${poses?.saved ?? 0} saved  /  ${poses?.reason ?? 'Ready'}`}</p>
    {poses && poses.rejected > 0 && <div aria-label="Screenshot rejections">
      <p>{poses.rejected} frames rejected. Last: {poses.last_rejection || 'Reason unavailable for this older capture'}</p>
      {Object.entries(poses.rejection_reasons ?? {}).map(([reason, count]) => <p key={reason}>{reason}: {count}</p>)}
    </div>}
    <details><summary>Review screenshots</summary>
      <p>Add clear, different poses to the existing player examples. You can add several; existing pictures stay available.</p>
      {available.length > 0 && <label className="player-example-select-all"><input type="checkbox"
        checked={chosen.length === available.length} disabled={locked}
        onChange={event => setChecked(event.target.checked ? available.map(candidate => candidate.id) : [])} />Select all</label>}
      <div className="player-example-grid">{poses?.candidates?.map((candidate, index) => <label className="player-example" key={candidate.id}>
        <img src={`data:image/png;base64,${candidate.crop}`} alt={`Player example ${index + 1}`} />
        <span><input type="checkbox" aria-label={`Select screenshot ${index + 1}`}
          disabled={locked || candidate.added} checked={!candidate.added && chosen.includes(candidate.id)}
          onChange={event => setChecked(previous => event.target.checked ? [...previous, candidate.id] : previous.filter(id => id !== candidate.id))} />
          {candidate.added ? 'Already added' : `Screenshot ${index + 1}`}</span>
      </label>)}</div>
      <p aria-live="polite">{chosen.length} selected</p>
      <button disabled={locked || !chosen.length} onClick={() => void run({ use_selected: chosen })}>Add selected to player examples</button>
    </details>
  </div>;
}
