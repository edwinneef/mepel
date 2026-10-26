import { useEffect, useState } from 'react';
import type { EngineClient } from './client';
import type { Snapshot } from './contracts';

interface Props {
  snapshot: Snapshot; client: EngineClient; disabled: boolean;
  act: (operation: () => Promise<unknown>) => Promise<void>;
  availableAreas?: { id: string; name: string }[];
  selectOnly?: boolean;
}

/** One-step supervised route: pick a destination, click Go, then click into the game. */
export function GoBar({ snapshot: s, client, disabled, act, availableAreas, selectOnly }: Props) {
  const [maps, setMaps] = useState<{ id: string; name: string }[]>([]);
  const [mapId, setMapId] = useState('');
  const [target, setTarget] = useState('');
  const [refusal, setRefusal] = useState('');
  const position = s.position;
  const nav = s.navigation;
  const map = position && nav?.map && nav.map.area_id === position.area_id ? nav.map : null;
  const here = position?.kind === 'platform' ? position.surface_id : null;
  const name = (id?: string | null) => map?.nodes.find(node => node.id === id)?.name ?? id ?? '';
  useEffect(() => {
    if (availableAreas || position || maps.length) return;
    client.command<{ areas: { id: string; name: string }[] }>('area_list')
      .then(result => setMaps(result.areas)).catch(() => undefined);
  }, [client, position, maps.length, availableAreas]);
  const send = (operation: () => Promise<unknown>) => act(async () => {
    setRefusal('');
    try { return await operation(); } catch (error) {
      setRefusal(error instanceof Error ? error.message : String(error));
      throw error;
    }
  });
  if (!position) {
    return <section className="go-bar" aria-label="Go to">
      <strong>Go to</strong>
      <select aria-label="Map to track" value={mapId} disabled={disabled} onChange={event => setMapId(event.target.value)}>
        <option value="">Choose the map you are on…</option>
        {(availableAreas ?? maps).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
      <button disabled={disabled || !mapId} onClick={() => void send(() => client.command('position_start', { area_id: mapId }))}>Track map</button>
      <span className={`go-status ${refusal ? 'warning-copy' : ''}`} role="status">{refusal || 'Track the map you are on to list destinations. No keys are sent.'}</span>
    </section>;
  }
  const status = nav?.active
    ? `${nav.stage === 'countdown' ? 'Click into the game now · ' : ''}${nav.reason}`
    : refusal || (here ? `You are on ${name(here)}` : position.reason ?? 'Waiting for your position');
  return <section className="go-bar" aria-label="Go to">
    <strong>Go to</strong>
    {map ? <>
      <select aria-label="Go destination" value={target} disabled={disabled || Boolean(nav?.active)} onChange={event => setTarget(event.target.value)}>
        <option value="">Choose a platform…</option>
        {map.nodes.filter(node => node.kind === 'platform' && !node.excluded && node.id !== here)
          .map(node => <option key={node.id} value={node.id}>{node.name}</option>)}
      </select>
      <button className="primary" disabled={disabled || !target || Boolean(nav?.active)} onClick={() => void send(() => client.command('nav_go', { target, opt_in: true }))}>{selectOnly ? 'Select destination (I’m supervising)' : "Go (I'm supervising)"}</button>
    </> : <button disabled={disabled} onClick={() => void send(() => client.command('nav_refresh'))}>Load routes for {position.area_name ?? 'this map'}</button>}
    <span className={`go-status ${refusal ? 'warning-copy' : ''}`} role="status">{status}</span>
  </section>;
}
