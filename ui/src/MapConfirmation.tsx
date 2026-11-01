import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import type { Snapshot } from './contracts';
import type { ViewImage } from './useViewport';
import './mapConfirmation.css';

const STORAGE_KEY = 'maple-map-confirmation';

function savedConfirmation(): string | null {
  try { return sessionStorage.getItem(STORAGE_KEY); } catch { return null; }
}

function saveConfirmation(key: string | null) {
  try {
    if (key) sessionStorage.setItem(STORAGE_KEY, key);
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch { /* Confirmation still works for this mounted panel. */ }
}

interface Props {
  snapshot: Snapshot; image?: ViewImage | null; revision: number;
  disabled: boolean; onWrongMap: () => void; overlay: ReactNode;
}

/** A session acknowledgement only. It never changes engine readiness or sends input. */
export function MapConfirmation({ snapshot: s, image, revision, disabled, onWrongMap, overlay }: Props) {
  const position = s.position;
  const identity = JSON.stringify([s.instance_id, s.session_id, s.frame.source_id,
    position?.area_id, revision, position?.teaching?.map_revision ?? null,
    s.catalog?.active_map ?? null, Boolean(s.area_editing)]);
  const [accepted, setAccepted] = useState(savedConfirmation);
  useEffect(() => {
    if (savedConfirmation() !== identity) saveConfirmation(null);
    setAccepted(savedConfirmation());
  }, [identity]);
  const confirmed = accepted === identity;
  const alignment = position?.map_alignment;
  const precise = alignment ? alignment.state === 'ready' && alignment.precision_verified
    : position?.calibrated === true;
  const fresh = Boolean(s.frame.id) && s.frame.available && s.frame.age_ms != null
    && s.frame.age_ms >= 0 && s.frame.age_ms <= 500
    && position?.stale === false && position.captured_at != null
    && s.frame.captured_at != null && Math.abs(s.frame.captured_at - position.captured_at) <= 0.5;
  const pictureMatches = Boolean(image && image.sourceId === s.frame.source_id
    && image.capturedAt != null && position?.captured_at != null
    && Math.abs(image.capturedAt - position.captured_at) <= 0.5);
  const located = position?.kind === 'platform' || position?.kind === 'rope';
  const mapKnown = Boolean(s.catalog?.active_map && !s.catalog.map_filter_error && !s.catalog.map_filter_held);
  const ready = mapKnown && fresh && pictureMatches && precise && located && !position?.provisional
    && Boolean(position?.canvas && position.marker && position.feet)
    && !s.area_editing && !s.calibrating && !position?.calibration?.active;
  const reason = !mapKnown ? 'Waiting for a readable map name.'
    : !fresh ? 'Waiting for a fresh position reading.'
    : !pictureMatches ? 'Waiting for a matching game picture.'
    : !ready ? 'Waiting for passive alignment. Movement stays locked while position is uncertain.'
    : confirmed ? 'Map confirmed. Movement still uses the existing safety checks.'
    : 'Check the map name and highlighted player spot, then confirm.';
  const forget = () => { saveConfirmation(null); setAccepted(null); onWrongMap(); };
  return <div className="map-confirmation" aria-label="Check map">
    <h3>{confirmed ? 'Map confirmed' : 'Check map'}</h3>
    <strong>{s.catalog?.active_map ?? position?.area_name}</strong>
    {s.catalog?.active_map && s.catalog.active_map !== position?.area_name && <p>Saved map: {position?.area_name}</p>}
    {image && <div className="map-confirmation-picture">
      <img src={image.url} alt={pictureMatches && fresh ? 'Current map picture' : 'Last map picture · waiting for a fresh match'}
        width={image.width} height={image.height} draggable={false} />
      {pictureMatches && fresh && <svg viewBox={`0 0 ${image.width} ${image.height}`}
        role="img" aria-label="Estimated player spot">{overlay}</svg>}
    </div>}
    <p role="status">{reason}</p>
    {!confirmed && <p>No walking calibration or route teaching is needed. This step sends no game keys.</p>}
    <div className="button-grid">
      <button className="primary" disabled={disabled || !ready || confirmed} onClick={() => {
        saveConfirmation(identity); setAccepted(identity);
      }}>{confirmed ? 'Confirmed' : 'Confirm map'}</button>
      <button disabled={disabled} onClick={forget}>Wrong map</button>
    </div>
  </div>;
}
