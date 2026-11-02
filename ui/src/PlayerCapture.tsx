import { useState } from 'react';
import type { Snapshot } from './contracts';
import type { EngineClient } from './client';

export function PlayerCapture({ snapshot, client, act, disabled }: {
  snapshot: Snapshot; client: EngineClient; disabled: boolean;
  act: (operation: () => Promise<unknown>) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const poses = snapshot.pose_collection;
  const identities = poses?.identities ?? [];
  const [identity, setIdentity] = useState('');
  const selected = identities.includes(identity) ? identity : identities.length === 1 ? identities[0] : '';
  const run = async (payload: Record<string, unknown>) => {
    setBusy(true);
    try { await act(() => client.command('pose_collection', payload)); }
    finally { setBusy(false); }
  };
  return <div aria-label="Player screenshots">
    {identities.length > 1 && <label>Player name<select aria-label="Screenshot player" value={selected} disabled={busy || poses?.enabled} onChange={e => setIdentity(e.target.value)}>
      <option value="">Select taught name</option>{identities.map(name => <option key={name}>{name}</option>)}
    </select></label>}
    <button disabled={disabled || busy || !poses || (!poses.enabled && (!selected || poses.pending > 0))}
      onClick={() => void run(poses?.enabled ? { enabled: false } : { enabled: true, identity: selected, outfit: `capture-${Date.now()}` })}>
      {poses?.enabled ? 'Cancel screenshot capture' : 'Capture player screenshots'}</button>
    <p aria-live="polite">{!identities.length ? 'Add a name tag in Tracking first.' : poses?.enabled ? `${poses.saved}/${poses.limit} saved  /  ${poses.reason}  /  stops after 30 seconds` : `${poses?.saved ?? 0} saved  /  ${poses?.reason ?? 'Ready'}`}</p>
    <details><summary>Review screenshots</summary>
      <p>Capture sends no keys. Use clear appearances with the full player and feet visible.</p>
      {poses?.candidates?.map(candidate => <div key={candidate.id}>
        <img src={`data:image/png;base64,${candidate.crop}`} alt="Captured player appearance" />
        <button disabled={disabled || busy || poses.enabled || poses.pending > 0} onClick={() => void run({ use: candidate.id })}>Use for recognition</button>
      </div>)}
    </details>
  </div>;
}
