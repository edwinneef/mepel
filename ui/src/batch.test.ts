import { expect, it } from 'vitest';
import { batchReport } from './batch';

it('explains a failed run in full: why, how the engine stopped and what to do', () => {
  const output = ['Starting', JSON.stringify({ outcome: 'failure', error: 'Game lost focus',
    stop: { code: 'FOCUS_LOST', message: 'MapleStory is not focused; input released' },
    stop_error: null, proven_after: 3, misses: [['fh1', 'fh2']] }), 'Control returned to operator.'].join('\n');
  expect(batchReport({ running: false, code: 1, output })).toEqual({ tone: 'fail', headline: 'Run failed',
    detail: ['Why: Game lost focus', 'Engine stop (FOCUS_LOST): MapleStory is not focused; input released',
      '3 moves proven · 1 missed move landed safely',
      'Keys released, clip saved. Move to safety; no automatic retry.'].join('\n') });
  expect(batchReport({ running: false, code: 1, output: '{"blocked": "Stand still first", "input_sent": false}' }))
    .toEqual({ tone: 'fail', headline: 'Not started · no keys sent', detail: 'Stand still first' });
  expect(batchReport({ running: false, code: 0, output: '{"outcome": "functional_success", "proven_after": 2}' }))
    .toEqual({ tone: 'ok', headline: 'Finished the full session', detail: '2 moves proven' });
});
