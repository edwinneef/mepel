import './PlayerCapture.css';
import { useState } from 'react';
import type { Snapshot } from './contracts';
import type { EngineClient } from './client';

export function PlayerCapture({ snapshot, client, act, disabled }: {
  snapshot: Snapshot; client: EngineClient; disabled: boolean;
  act: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [checked, setChecked] = useState<string[]>([]);
  const poses = snapshot.pose_collection;
  const identities = poses?.identities ?? [];
  const [identity, setIdentity] = useState('');
  const selected = identities.includes(identity) ? identity : identities.includes(poses?.identity ?? '') ? poses!.identity : identities.length === 1 ? identities[0] : '';
  const available = (poses?.candidates ?? []).filter(candidate => !candidate.added);
  const chosen = checked.filter(id => available.some(candidate => candidate.id === id));
  const locked = disabled || busy || Boolean(poses?.enabled) || Boolean(poses?.pending);
  const run = async (payload: Record<string, unknown>) => {
    setBusy(true);
    try { await act(() => client.command('pose_collection', payload)); }
    finally { setBusy(false); }
  };
  return <div aria-label="Player screenshots">
    {identities.length > 1 && <div className="player-picker">
      <button type="button" className="player-picker-toggle" aria-expanded={choosing}
        disabled={disabled || busy || poses?.enabled} onClick={() => setChoosing(!choosing)}>
        <span>{selected ? `Taught name ${identities.indexOf(selected) + 1}` : 'Select taught name'}</span><span aria-hidden="true">{choosing ? '^' : 'v'}</span>
      </button>
      {choosing && <div className="player-picker-options" role="group" aria-label="Taught names">
        {identities.map((name, index) => <button key={name} type="button" title={name}
          aria-pressed={selected === name} disabled={disabled || busy || poses?.enabled}
          onClick={() => { setIdentity(name); setChoosing(false); }}>Taught name {index + 1}{selected === name ? ' (selected)' : ''}</button>)}
      </div>}
    </div>}
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
