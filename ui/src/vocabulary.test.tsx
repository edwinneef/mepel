import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { botState, firstBlocker, startChecks, statusSentence } from './vocabulary';
import { CheckList, LoopChooser, PlanPicker, displayKey } from './ClearParts';
import type { Snapshot } from './contracts';

const snapshot = (overrides: Partial<Snapshot> = {}) => ({
  focused: true, player: { kind: 'player', box: { x: 0, y: 0, width: 1, height: 1 }, confidence: 1, template: '', tracked: false },
  position: { area_id: 'a1', kind: 'platform', reason: '', input_sent: false },
  required_probes: ['left'], probes: { left: { confirmed: true }, hp_potion: { confirmed: true } },
  readiness: { preview: { ready: true, reason: 'Ready' }, combat: { ready: true, reason: 'Ready' }, potions: { ready: true, reason: '' } },
  ...overrides,
}) as unknown as Snapshot;

describe('vocabulary', () => {
  it('maps overlay status codes to the shared state words', () => {
    expect(botState('OFF')).toBe('off');
    expect(botState('ON')).toBe('running');
    expect(botState('OFF', true)).toBe('running');
    expect(botState('BLOCKED')).toBe('alarm');
    expect(botState('DISCONNECTED', true)).toBe('disconnected');
  });

  it('is ready only when every check and the engine gate pass', () => {
    const checks = startChecks(snapshot(), { connected: true, plan: 'loop', loops: 1 });
    expect(firstBlocker(checks)).toBeNull();
    expect(statusSentence('off', null, { plan: 'loop', loop: 'Snail loop', minutes: 15 }).headline).toBe('Ready to hunt');
  });

  it('names the first missing thing in plain words', () => {
    const missingPlayer = startChecks(snapshot({ player: null }), { connected: true, plan: 'platform' });
    expect(statusSentence('off', firstBlocker(missingPlayer), { plan: 'platform', minutes: 1 }).headline)
      .toBe("Can't start: the character isn't recognised");
    const untested = startChecks(snapshot({ probes: { left: { confirmed: true }, hp_potion: { confirmed: false } } }), { connected: true, plan: 'watch' });
    expect(firstBlocker(untested)?.miss).toBe("the HP potion key isn't tested");
    const noLoop = startChecks(snapshot(), { connected: true, plan: 'loop', loops: 0 });
    expect(firstBlocker(noLoop)?.id).toBe('loop');
    const behind = startChecks(snapshot({ focused: false }), { connected: true, plan: 'watch' });
    expect(firstBlocker(behind)?.action).toBe('focus_game');
  });

  it('never claims ready when the engine gate refuses', () => {
    const s = snapshot({ readiness: { preview: { ready: true, reason: '' }, combat: { ready: false, reason: 'Waiting for fresh recognition.' }, potions: { ready: true, reason: '' } } });
    const blocker = firstBlocker(startChecks(s, { connected: true, plan: 'platform' }));
    expect(blocker?.id).toBe('gate');
    expect(blocker?.miss).toBe('waiting for fresh recognition');
    expect(firstBlocker(startChecks(s, { connected: true, plan: 'watch' }))).toBeNull();
  });

  it('reports a lost engine connection first', () => {
    expect(firstBlocker(startChecks(null, { connected: false, plan: 'watch' }))?.id).toBe('engine');
  });
});

describe('shared parts', () => {
  it('offers the one-click fix only for the focus check', () => {
    const actions: string[] = [];
    render(<CheckList checks={startChecks(snapshot({ focused: false }), { connected: true, plan: 'watch' })} onAction={a => actions.push(a)} />);
    fireEvent.click(screen.getByRole('button', { name: 'Bring game to front' }));
    expect(actions).toEqual(['focus_game']);
  });

  it('cycles saved loops with buttons and picks a plan', () => {
    const picked: string[] = [];
    render(<LoopChooser plan="loop" loops={[{ id: 'a', name: 'Snail loop', stops: 4 }, { id: 'b', name: 'Top shelf', stops: 2 }]}
      selected="a" onSelect={id => picked.push(id)} />);
    fireEvent.click(screen.getByRole('button', { name: 'Next loop' }));
    fireEvent.click(screen.getByRole('button', { name: 'Previous loop' }));
    expect(picked).toEqual(['b', 'b']);
    const plans: string[] = [];
    render(<PlanPicker plan="loop" onPlan={p => plans.push(p)} available={{ platform: 'Input locked' }} />);
    expect(screen.getByRole('radio', { name: /Stay on this platform/ })).toHaveProperty('disabled', true);
    fireEvent.click(screen.getByRole('radio', { name: /Watch only/ }));
    expect(plans).toEqual(['watch']);
  });

  it('shows config key names as they read on a keyboard', () => {
    expect(['insert', 'f8', 'a', 'ctrl', 'pagedown'].map(displayKey)).toEqual(['Insert', 'F8', 'A', 'Ctrl', 'Page Down']);
  });
});
