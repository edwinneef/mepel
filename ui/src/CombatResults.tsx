import type { CombatEvidence } from './contracts';

export function CombatResults({ evidence }: { evidence: CombatEvidence | null | undefined }) {
  const save = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(evidence, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `bowman-${evidence!.session_id}-${evidence!.run}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <section className="tool-group" aria-label="Demo outcome">
    <h3>What happened</h3>
    {!evidence ? <p>No demo evidence yet. Select a probe or preview first.</p> : <>
      <p>{evidence.activity} · {new Date(evidence.started_at * 1000).toLocaleTimeString()}</p>
      <strong>{evidence.stop_reason ? `Stopped: ${evidence.stop_reason}` : 'Run in progress'}</strong>
      <p>Hit outcome unconfirmed. Completed input does not prove damage; an enemy disappearing does not prove a kill.</p>
      <ul>{evidence.events.slice(-6).map((event, i) => <li key={`${event.time}:${i}`}>
        {event.kind === 'observed_effect' ? 'Observed control effect: ' : event.kind === 'observed_bar_gain' ? 'Observed bar change: ' : ''}
        {event.detail}{event.before != null && event.after != null && ` (${event.before}% → ${event.after}%)`}
      </li>)}</ul>
      <button onClick={save}>Save run evidence</button>
      <details><summary>Frames and observed distances</summary>
        <p>Distances belong to the observation recorded alongside an event; they do not prove where a projectile hit. At most 64 recent events are retained until the next run or engine restart.</p>
        <ol>{evidence.events.map((event, i) => <li key={i}>
          {new Date(event.time * 1000).toLocaleTimeString()} · {event.detail}
          <small> {event.observation.frame_id ?? 'No frame yet'}</small>
          {event.observation.same_platform_targets?.map((target, j) => <span key={j}> · {target.direction} {target.distance_px.toFixed(1)} px</span>)}
        </li>)}</ol>
      </details>
    </>}
  </section>;
}
