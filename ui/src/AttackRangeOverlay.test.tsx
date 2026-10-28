import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { AttackRangeOverlay } from './AttackRangeOverlay';
import { snapshot } from './test-fixtures';

afterEach(cleanup);
const player = snapshot().player!;
const setup = { minimum_px: 40, maximum_px: 180, measured: false, reason: '' };

it('draws both horizontal bands from the player centre in native pixels', () => {
  render(<svg><AttackRangeOverlay player={player} setup={setup} /></svg>);
  const guide = screen.getByLabelText('Configured attack range');
  const bands = guide.querySelectorAll('rect');
  // Player centre is 465; bands span 285..425 and 505..645.
  expect([...bands].map(rect => [rect.getAttribute('x'), rect.getAttribute('width')]))
    .toEqual([['285', '140'], ['505', '140'], ['425', '80']]);
  expect(screen.getByText('Attack 40–180 px · unmeasured')).toBeTruthy();
  expect(guide.getAttribute('pointer-events')).toBe('none');
});

it('hides uncertain or tracked players and invalid or missing tuning', () => {
  const { rerender } = render(<svg><AttackRangeOverlay player={{ ...player, tracked: true }} setup={setup} /></svg>);
  expect(screen.queryByLabelText('Configured attack range')).toBeNull();
  rerender(<svg><AttackRangeOverlay player={player} threshold={0.99} setup={setup} /></svg>);
  expect(screen.queryByLabelText('Configured attack range')).toBeNull();
  rerender(<svg><AttackRangeOverlay player={player} setup={{ ...setup, maximum_px: 20 }} /></svg>);
  expect(screen.queryByLabelText('Configured attack range')).toBeNull();
  rerender(<svg><AttackRangeOverlay player={player} setup={undefined} /></svg>);
  expect(screen.queryByLabelText('Configured attack range')).toBeNull();
});
