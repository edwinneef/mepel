import { useEffect, useRef, useState } from 'react';
import type { AreaProfile } from './contracts';
import type { EngineClient } from './client';
import { PathBuilder } from './PathBuilder';
import type { FarmingRoute } from './PathBuilder';
import type { RouteOptions } from './pathPlanning';

type Loaded = { profile: AreaProfile; map_hash: string } & RouteOptions;
const text = (error: unknown) => error instanceof Error ? error.message : String(error);
// The client refuses a command while another is in flight; that is a wait, not a failure.
const BUSY = /Wait for the current operation to finish/;
const RETRIES = 10, RETRY_MS = 300;
const LOADING = 'Loading movement geometry…';

/** Saved maps load by themselves; the map the player stands on is preselected and opens at once. */
export function PathBuilderLibrary({ client, disabled, initialArea, onSelect, player }: {
  client: EngineClient; disabled: boolean; initialArea?: string;
  onSelect?: (route: FarmingRoute | null) => void;
  /** Where the player stands; drawn only on the map they are on. */
  player?: { area: string; feet: [number, number]; stale: boolean } | null;
}) {
  const [areas, setAreas] = useState<{ id: string; name: string }[] | null>(null);
  const [chosen, setChosen] = useState(initialArea ?? '');
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const retries = useRef(0);
  // A busy refusal retries by itself a few times; only a real failure needs Try again.
  const retryLater = (error: unknown, reset: () => void) => {
    if (!BUSY.test(text(error)) || retries.current >= RETRIES) { setMessage(text(error)); return; }
    retries.current++; reset();
    setTimeout(() => setAttempt(value => value + 1), RETRY_MS);
  };
  // One request per chosen map and retry; never re-request because of what the reply contains.
  const requested = useRef('');
  // Each engine command briefly marks the session busy, which disables this builder. So a
  // request is made once per map (or list) and retry, and a busy blip never cancels or repeats
  // it; otherwise every reply would trigger the next request.
  const listed = useRef(-1);
  useEffect(() => {
    if (disabled || areas || listed.current === attempt) return;
    listed.current = attempt;
    void client.command<{ areas: { id: string; name: string }[] }>('area_list')
      .then(value => { retries.current = 0; setAreas(value.areas ?? []); })
      .catch(error => retryLater(error, () => { listed.current = -1; }));
  }, [client, disabled, areas, attempt]);
  const latest = useRef(chosen);
  latest.current = chosen;
  useEffect(() => {
    // Engine route commands are refused while the bot runs; wait until it is usable again.
    const key = `${chosen}:${attempt}`;
    // Wait for the map list: both requests at once make the second one busy.
    if (!chosen || disabled || (!areas && !message) || requested.current === key) return;
    requested.current = key;
    setBusy(true); setMessage(LOADING);
    void client.command<Loaded>('farm_route_map', { area_id: chosen })
      .then(value => {
        if (latest.current !== chosen) return;
        retries.current = 0;
        if (value?.profile) { setLoaded(value); setMessage(''); } else setMessage('The engine sent no map for this area.');
      })
      .catch(error => { if (latest.current === chosen) retryLater(error, () => { requested.current = ''; }); })
      .finally(() => setBusy(false));
  }, [client, chosen, disabled, attempt, areas, message]);
  const known = areas?.some(area => area.id === chosen);
  return <section aria-label="Saved farming circuits">
    <h3>1. Choose a map</h3>
    <p>The map you are on opens automatically. Pick another saved map to build a path there. You can build paths while the bot is Off.</p>
    <div className="path-toolbar"><label>Map for path builder <select value={chosen} disabled={disabled || busy || !areas} onChange={event => { setChosen(event.target.value); setLoaded(null); onSelect?.(null); }}>
      <option value="">{areas ? (areas.length ? 'Choose a saved map' : 'No saved maps yet') : 'Loading saved maps…'}</option>
      {chosen && areas && !known && <option value={chosen}>Current map</option>}
      {areas?.map(area => <option key={area.id} value={area.id}>{area.name}</option>)}
    </select></label>
      {message && message !== LOADING && !busy && <button disabled={disabled} onClick={() => { setMessage(''); retries.current = 0; setAttempt(value => value + 1); }}>Try again</button>}</div>
    {message && <p role="status">{message}</p>}
    {loaded && <PathBuilder key={loaded.profile.id} profile={loaded.profile} mapHash={loaded.map_hash}
      options={loaded} client={client} disabled={disabled || busy} onSelect={onSelect}
      player={player?.area === loaded.profile.id ? player : null} />}
  </section>;
}
