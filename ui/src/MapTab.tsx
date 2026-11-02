import type { EngineClient } from './client';
import type { Snapshot } from './contracts';
import { useHeldPosition } from './heldPosition';
import { PathBuilderLibrary } from './PathBuilderLibrary';
import type { FarmingRoute } from './PathBuilder';

interface Props {
  snapshot: Snapshot; client: EngineClient; disabled: boolean;
  onCircuit?: (route: FarmingRoute | null) => void;
  builderDisabled?: boolean;
  /** False while this tab is mounted but hidden; the path builder then makes no requests. */
  active?: boolean;
}

/** The map page is the path builder: every farming route is built and chosen here. */
export function MapTab({ snapshot: s, client, disabled, onCircuit, builderDisabled = disabled, active = true }: Props) {
  const spot = useHeldPosition(s.position);
  const areaId = s.position?.area_id;
  const nav = s.navigation;
  const map = nav?.map && nav.map.area_id === areaId ? nav.map : null;
  const name = spot.surface ? (map?.nodes.find(node => node.id === spot.surface)?.name ?? spot.surface) : '';
  const heading = !areaId ? 'Track a map to build a path'
    : spot.kind === 'rope' ? `You're on a rope (${name}); stand on a platform to farm`
    : spot.surface ? `You are on ${name}` : 'Where you are is unknown';
  return <section className="map-tab" aria-label="Map">
    {s.position?.area_name && <span className="eyebrow">{s.position.area_name}</span>}
    <h3>{heading}</h3>
    <PathBuilderLibrary client={client} disabled={!active || builderDisabled || Boolean(nav?.active) || s.mode !== 'capture'}
      initialArea={areaId} onSelect={onCircuit}
      player={spot.feet && areaId ? { area: areaId, feet: spot.feet, stale: spot.held } : null} />
  </section>;
}
