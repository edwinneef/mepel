import { useEffect, useRef, useState } from 'react';
import type { EngineClient } from './client';
import type { Snapshot } from './contracts';
import { PathBuilderLibrary } from './PathBuilderLibrary';
import type { FarmingRoute } from './PathBuilder';

interface Props {
  snapshot: Snapshot; client: EngineClient; disabled: boolean;
  onCircuit?: (route: FarmingRoute | null) => void;
  builderDisabled?: boolean;
  /** False while this tab is mounted but hidden; the path builder then makes no requests. */
  active?: boolean;
}

// Status marks a reading stale after 0.5 s; at ~2.5 fps that is every other update.
// The map keeps the last position this long (faded) instead of blinking.
const HOLD_MS = 2000;

/** The map page is the path builder: every farming route is built and chosen here. */
export function MapTab({ snapshot: s, client, disabled, onCircuit, builderDisabled = disabled, active = true }: Props) {
  const live = s.position?.feet ?? null;
  const last = useRef<{ feet: [number, number]; area?: string; at: number } | null>(null);
  const [, tick] = useState(0);
  if (live) last.current = { feet: live, area: s.position?.area_id, at: Date.now() };
  useEffect(() => {
    if (live) return;
    const timer = setTimeout(() => tick(n => n + 1), HOLD_MS);
    return () => clearTimeout(timer);
  }, [live]);
  const areaId = s.position?.area_id;
  const nav = s.navigation;
  const held = !live && last.current && last.current.area === areaId
    && Date.now() - last.current.at < HOLD_MS ? last.current.feet : null;
  const feet = live ?? held;
  const kind = s.position?.kind;
  const here = kind === 'platform' || kind === 'rope' ? s.position?.surface_id : null;
  const map = nav?.map && nav.map.area_id === areaId ? nav.map : null;
  const name = here ? (map?.nodes.find(node => node.id === here)?.name ?? here) : '';
  const heading = !areaId ? 'Track a map to build a path'
    : kind === 'rope' ? `You're on a rope (${name}); stand on a platform to farm`
    : here ? `You are on ${name}` : 'Where you are is unknown';
  return <section className="map-tab" aria-label="Map">
    {s.position?.area_name && <span className="eyebrow">{s.position.area_name}</span>}
    <h3>{heading}</h3>
    <PathBuilderLibrary client={client} disabled={!active || builderDisabled || Boolean(nav?.active) || s.mode !== 'capture'}
      initialArea={areaId} onSelect={onCircuit}
      player={feet && areaId ? { area: areaId, feet, stale: !live } : null} />
  </section>;
}
