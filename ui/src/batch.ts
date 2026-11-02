import type { FarmingRoute } from './PathBuilder';

/** Saved farming paths for the player's map, as the overlay last read them. */
export type PathAvailability =
  | { state: 'unknown' } | { state: 'loading' } | { state: 'error'; message: string }
  | { state: 'ready'; names: string[]; routes?: FarmingRoute[] };

export interface BatchState { running: boolean; kind?: string; line?: string; output?: string; code?: number;
  /** A dashboard start the in-game overlay has not taken yet. */
  pending?: boolean }

export interface BatchReport { tone: 'ok' | 'fail' | 'info'; headline: string; detail: string }

/** What happened in the last batch, in plain words: a one-line headline and the reasons. */
export function batchReport(batch: BatchState): BatchReport | null {
  const text = (batch.output ?? batch.line ?? '').trim();
  if (!text) return null;
  const lines = text.split(/\r?\n/).filter(Boolean);
  for (const line of [...lines].reverse()) {
    let value: Record<string, unknown>;
    try { value = JSON.parse(line) as Record<string, unknown>; } catch { continue; }
    if (typeof value.blocked === 'string') {
      return { tone: 'fail', headline: 'Not started · no keys sent', detail: value.blocked };
    }
    if (typeof value.outcome !== 'string' && typeof value.error !== 'string') continue;
    const stop = (value.stop ?? {}) as { code?: string; message?: string };
    const misses = Array.isArray(value.misses) ? value.misses.length : 0;
    const extras = [
      typeof value.proven_after === 'number' ? `${value.proven_after} moves proven` : '',
      misses ? `${misses} missed ${misses === 1 ? 'move' : 'moves'} landed safely` : '',
    ].filter(Boolean).join(' · ');
    if (value.outcome === 'functional_success') {
      return { tone: 'ok', headline: 'Finished the full session', detail: extras };
    }
    if (value.outcome === 'nothing_left') {
      return { tone: 'ok', headline: 'Nothing left to do · stopped cleanly', detail: extras };
    }
    const reasons = [
      typeof value.error === 'string' && value.error ? `Why: ${value.error}` : '',
      stop.message && stop.message !== value.error ? `Engine stop${stop.code ? ` (${stop.code})` : ''}: ${stop.message}` : '',
      typeof value.stop_error === 'string' && value.stop_error ? `Stop problem: ${value.stop_error}` : '',
      extras,
      batch.code !== undefined && batch.code !== 0 ? 'Keys released, clip saved. Move to safety; no automatic retry.' : '',
    ].filter(Boolean);
    return value.outcome === 'safe_stop'
      ? { tone: 'info', headline: 'Stopped safely', detail: reasons.join('\n') }
      : { tone: 'fail', headline: 'Run failed', detail: reasons.join('\n') || 'No reason was reported; see the result file.' };
  }
  return { tone: batch.code ? 'fail' : 'info', headline: batch.code ? 'Run ended with an error' : 'Last batch',
    detail: lines.slice(-3).join('\n') };
}
