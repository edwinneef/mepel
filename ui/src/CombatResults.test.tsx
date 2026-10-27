import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { CombatResults } from './CombatResults';

afterEach(cleanup);

it('retains stopped outcomes without treating input completion as a hit', () => {
  render(<CombatResults evidence={{ session_id: 'session', run: 1, activity: 'probe:attack',
    started_at: 100, stop_reason: 'F8 pressed', hit_confirmed: null,
    events: [{ time: 101, kind: 'input_outcome', detail: 'attack completed',
      observation: { frame_id: 'session:3', same_platform_targets: [{ distance_px: 130, direction: 'right' }] } },
    { time: 102, kind: 'observed_bar_gain', detail: 'HP probe gain', before: 40, after: 60, observation: {} }],
  }} />);
  expect(screen.getByText('Stopped: F8 pressed')).toBeTruthy();
  expect(screen.getByText(/Hit outcome unconfirmed/)).toBeTruthy();
  expect(screen.getByText(/Observed bar change: HP probe gain/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Save run evidence' })).toBeTruthy();
  expect(screen.getByText(/right 130.0 px/)).toBeTruthy();
});
