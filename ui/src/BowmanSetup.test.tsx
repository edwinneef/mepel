import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { BowmanSetup } from './BowmanSetup';
import { EngineClient } from './client';
import { snapshot } from './test-fixtures';

afterEach(cleanup);

it('selects without a command, then explicitly applies one range choice without starting input', async () => {
  const client = new EngineClient('token');
  const command = vi.spyOn(client, 'command').mockResolvedValue({ ok: true });
  const s = { ...snapshot(), attack_setup: {
    minimum_px: 120, maximum_px: 250, measured: false, reason: '', profile: 'classic_bow',
    profiles: [
      { id: 'classic_bow', label: 'Bow / crossbow + Arrow Blow', minimum_px: 120, maximum_px: 250 },
      { id: 'classic_spear', label: 'Spear', minimum_px: 0, maximum_px: 100 },
    ],
  } };
  render(<BowmanSetup snapshot={s} client={client} disabled={false}
    act={async operation => { await operation(); }}
    selected={() => ({ id: 'frame', x: 0, y: 0, width: 1, height: 1 })} clear={vi.fn()}
    runMode="preview" setRunMode={vi.fn()} onSetup={vi.fn()} />);
  expect(screen.getByText('Classic baseline · conservative operating band')).toBeTruthy();
  expect(screen.queryByText(/Do not start combat with unmeasured tuning/)).toBeNull();
  fireEvent.change(screen.getByLabelText('Classic weapon'), { target: { value: 'classic_spear' } });
  expect(command).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Apply weapon range' }));
  expect(command).toHaveBeenCalledExactlyOnceWith('range_profile', { profile: 'classic_spear' });
});
