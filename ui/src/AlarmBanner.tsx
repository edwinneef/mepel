import { useEffect, useRef, useState } from 'react';
import type { Snapshot } from './contracts';

interface Props { snapshot: Snapshot; onAcknowledge: (id: string) => void; showAcknowledge?: boolean }

export function AlarmBanner({ snapshot, onAcknowledge, showAcknowledge = true }: Props) {
  const [fallback, setFallback] = useState(false);
  const [copied, setCopied] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const active = snapshot.alarm.active;
  const visible = active || Boolean(snapshot.stop && !snapshot.stop.acknowledged);
  const details = JSON.stringify(snapshot.stop ?? snapshot.alarm, null, 2);
  useEffect(() => { if (fallback) { textarea.current?.focus(); textarea.current?.select(); } }, [fallback]);
  useEffect(() => { setCopied(false); setFallback(false); }, [details]);
  if (!visible) return null;
  const id = snapshot.alarm.incident_id ?? snapshot.stop?.id;
  const copy = async () => {
    try { await navigator.clipboard.writeText(details); setCopied(true); }
    catch { setFallback(true); }
  };
  return <section className="alarm-banner" aria-label="Safety stop">
    <div><span className="eyebrow">Safety stop</span><p>{snapshot.stop?.message ?? 'Alarm active. Acknowledge to silence it.'}</p></div>
    {active && showAcknowledge && <button className="danger" onClick={() => id && onAcknowledge(id)} disabled={!id}>Acknowledge alarm</button>}
    <details><summary>Details</summary><pre>{details}</pre><button onClick={() => void copy()}>Copy alarm</button>
      {copied && <small role="status">Alarm copied.</small>}
      {fallback && <><small role="status">Press Ctrl+C to copy the selected details.</small>
        <textarea ref={textarea} readOnly value={details} aria-label="Alarm details to copy" rows={5} /></>}
    </details>
  </section>;
}
