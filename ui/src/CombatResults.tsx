import type { CombatEvidence } from './contracts';
import type { PotionEvidence, PotionRecord } from './potionEvidence';

const potionResults: Record<string, string> = {
  queued: 'Pending · potion input queued',
  awaiting_observation: 'Pending · waiting for a fresh bar reading',
  observed_bar_gain: 'Bar gain observed · potion recovery unverified',
  no_observed_gain: 'No bar gain observed · potion recovery unverified',
  baseline_unavailable: 'Incomplete · no usable before reading',
  observation_unavailable: 'Incomplete · no usable after reading',
  input_not_completed: 'Incomplete · potion input did not complete',
  outcome_unavailable: 'Incomplete · input outcome unavailable',
  source_changed: 'Incomplete · capture view changed',
  superseded: 'Incomplete · another potion replaced this observation',
  capture_ended: 'Incomplete · capture ended before observation finished',
};

function PotionResult({ resource, record }: { resource: string; record?: PotionRecord }) {
  return <li>
    <strong>{resource.toUpperCase()}: {record
      ? potionResults[record.status] ?? 'Incomplete · observation status unavailable'
      : 'Pending · no retained potion observation'}</strong>
    {record && <>
      {record.before && record.after && record.baseline_usable && <p>
        {record.before.percent.toFixed(1)}% → {record.after.percent.toFixed(1)}%
      </p>}
      <details><summary>{resource.toUpperCase()} observation details · ticket {record.ticket}</summary>
        <p>Input: {record.outcome?.result ?? 'Outcome not available'}</p>
        <p>Before: {record.before
          ? `${record.before.percent.toFixed(1)}% · ${record.before.frame}${record.baseline_usable ? '' : ' · baseline unusable'}`
          : 'Unavailable'}</p>
        <p>After: {record.after ? `${record.after.percent.toFixed(1)}% · ${record.after.frame}` : 'Unavailable'}</p>
        <p>Recording: {record.recording}</p>
        <p>Frame names identify retained observations; this panel does not verify that both PNGs reached disk.</p>
      </details>
    </>}
  </li>;
}

export function CombatResults({ evidence, potions }: {
  evidence: CombatEvidence | null | undefined; potions?: PotionEvidence | null;
}) {
  const save = () => {
    const result = { ...evidence, potion_evidence: potions ?? null };
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `combat-${evidence?.session_id ?? potions?.records[0]?.session_id ?? 'session'}-${evidence?.run ?? 'passive'}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <section className="tool-group" aria-label="Demo outcome">
    <h3>What happened</h3>
    {!evidence ? <p>No run evidence retained in this engine session. Previously accepted observations remain unchanged.</p> : <>
      <p>{evidence.activity} · {new Date(evidence.started_at * 1000).toLocaleTimeString()}</p>
      <strong>{evidence.stop_reason ? `Stopped: ${evidence.stop_reason}` : 'Run in progress'}</strong>
      <p>Hit outcome unconfirmed in this automatic report. Previously accepted hits remain accepted. Completed input does not prove damage; an enemy disappearing does not prove a kill.</p>
      <ul>{evidence.events.slice(-6).map((event, i) => <li key={`${event.time}:${i}`}>
        {event.kind === 'observed_effect' ? 'Observed control effect: ' : event.kind === 'observed_bar_gain' ? 'Observed bar change: ' : ''}
        {event.detail}{event.before != null && event.after != null && ` (${event.before}% → ${event.after}%)`}
      </li>)}</ul>
      <details><summary>Frames and observed distances</summary>
        <p>Distances belong to the observation recorded alongside an event; they do not prove where a projectile hit. At most 64 recent events are retained until the next run or engine restart.</p>
        <ol>{evidence.events.map((event, i) => <li key={i}>
          {new Date(event.time * 1000).toLocaleTimeString()} · {event.detail}
          <small> {event.observation.frame_id ?? 'No frame yet'}</small>
          {event.observation.same_platform_targets?.map((target, j) => <span key={j}> · {target.direction} {target.distance_px.toFixed(1)} px</span>)}
        </li>)}</ol>
      </details>
    </>}
    <h4>Passive potion evidence</h4>
    <p>{potions == null ? 'Passive evidence unavailable from this engine.'
      : potions.enabled ? 'Passive collection enabled.' : 'Passive collection disabled.'}
      {' '}Latest retained observations in this engine session may precede this run.</p>
    <ul>{(['hp', 'mp'] as const).map(resource => <PotionResult key={resource} resource={resource}
      record={potions?.records.filter(record => record.resource === resource).at(-1)} />)}</ul>
    <p>HP/MP recovery and basic-attack fallback remain unverified by this report. Bar gain can include regeneration or damage; no gain does not prove potion failure. Accepted controls are unchanged.</p>
    {(evidence || Boolean(potions?.records.length)) && <button onClick={save}>Save run evidence</button>}
  </section>;
}
