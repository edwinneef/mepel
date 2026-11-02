import { useState } from 'react';
import type { AreaProfile } from './contracts';
import type { EngineClient } from './client';
import { PathBuilder } from './PathBuilder';
import type { FarmingRoute } from './PathBuilder';

export function PathBuilderLibrary({ client, disabled, initialArea, onSelect }: {
  client: EngineClient; disabled: boolean; initialArea?: string;
  onSelect?: (route: FarmingRoute | null) => void;
}) {
  const [areas, setAreas] = useState<{ id: string; name: string }[]>([]);
  const [chosen, setChosen] = useState(initialArea ?? '');
  const [loaded, setLoaded] = useState<{ profile: AreaProfile; map_hash: string } | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  return <section aria-label="Saved farming circuits">
    <h3>1. Choose a map</h3>
    <p>Pick the map you want to farm. Then add the platforms you want to visit, in order. You can build this path while the bot is Off.</p>
    <div className="path-toolbar"><button disabled={disabled || busy} onClick={() => {
      setBusy(true); setMessage('');
      void client.command<{ areas: { id: string; name: string }[] }>('area_list')
        .then(value => setAreas(value.areas ?? []))
        .catch(error => setMessage(String(error))).finally(() => setBusy(false));
    }}>Load saved farming maps</button><label>Map for path builder <select value={chosen} disabled={disabled || busy} onChange={event => { setChosen(event.target.value); setLoaded(null); onSelect?.(null); }}>
      <option value="">Choose a saved map</option>{areas.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}
    </select></label>
      <button disabled={disabled || busy || !chosen} onClick={() => {
        setBusy(true); setMessage('Loading movement geometry…'); onSelect?.(null);
        void client.command<{ profile: AreaProfile; map_hash: string }>('farm_route_map', { area_id: chosen })
          .then(value => { setLoaded(value); setMessage(''); })
          .catch(error => setMessage(error instanceof Error ? error.message : String(error)))
          .finally(() => setBusy(false));
      }}>{busy ? 'Loading map…' : 'Open path builder'}</button></div>
    {message && <p role="status">{message}</p>}
    {loaded && <PathBuilder key={loaded.profile.id} profile={loaded.profile} mapHash={loaded.map_hash}
      client={client} disabled={disabled || busy} onSelect={onSelect} />}
  </section>;
}
