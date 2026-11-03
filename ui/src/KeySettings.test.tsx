import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { KeySettings, configKey } from './KeySettings';
import { snapshot } from './test-fixtures';
import type { EngineClient } from './client';

afterEach(() => cleanup());
const active = { hp_potion: 'insert', mp_potion: 'delete', pet_food: 'f', attack: 'ctrl', skill: 'ctrl', jump: 'alt',
  emergency_key: 'f8', start_stop: 'f6', drawings: 'f9', pet_feed_seconds: 600 };
const supported = ['a', 'f', 'home', 'insert', 'delete', 'ctrl', 'alt', 'space', 'f6', 'f7', 'f8', 'f9', 'f10'];
const view = (overrides = {}) => {
  const command = vi.fn(async () => ({ restart_required: true }));
  const onTest = vi.fn();
  const s = snapshot({ probes: { hp_potion: { confirmed: true }, mp_potion: { confirmed: false } },
    key_settings: { active, saved: active, restart_required: false, editable: true, supported, ...overrides } });
  render(<KeySettings snapshot={s} client={{ command } as unknown as EngineClient} disabled={false} onTest={onTest} />);
  return { command, onTest };
};

it('maps pressed keys to config names', () => {
  expect(['Control', 'Alt', ' ', 'F10', 'Home', 'PageDown', 'q', '7', 'Shift', 'Escape'].map(key => configKey({ key })))
    .toEqual(['ctrl', 'alt', 'space', 'f10', 'home', 'pagedown', 'q', '7', null, null]);
});

it('binds a key by pressing it, without the dashboard shortcuts seeing the press, and saves only changes', async () => {
  const { command } = view();
  const shortcut = vi.fn();
  window.addEventListener('keydown', shortcut);
  fireEvent.click(screen.getByRole('button', { name: 'HP potion key: insert. Change' }));
  expect(screen.getByText('Press a key…')).toBeTruthy();
  fireEvent.keyDown(window, { key: 'ArrowUp' });
  expect(screen.getByText('Arrow keys move the character and cannot be used here.')).toBeTruthy();
  fireEvent.keyDown(window, { key: 'Home' });
  expect(shortcut).not.toHaveBeenCalled();
  window.removeEventListener('keydown', shortcut);
  expect(screen.getByText('Not saved yet')).toBeTruthy();
  fireEvent.click(screen.getByRole('radio', { name: '5 min' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save keys' }));
  await waitFor(() => expect(command).toHaveBeenCalledWith('input_keys_set', { keys: { hp_potion: 'home', pet_feed_seconds: 300 } }));
  expect(await screen.findByText('Saved to config.toml. Restart the engine to use the new keys.')).toBeTruthy();
});

it('Esc cancels a key change and unsupported keys are refused', () => {
  const { command } = view();
  fireEvent.click(screen.getByRole('button', { name: 'Stop from anywhere key: f8. Change' }));
  fireEvent.keyDown(window, { key: 'Shift' });
  expect(screen.getByText(/Shift can't be pressed by the bot/)).toBeTruthy();
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(screen.getByText('Nothing changed.')).toBeTruthy();
  expect((screen.getByRole('button', { name: 'Save keys' }) as HTMLButtonElement).disabled).toBe(true);
  expect(command).not.toHaveBeenCalled();
});

it('requires pet food confirmation and explains the restart', () => {
  const { onTest } = view({ saved: { ...active, hp_potion: 'home' }, restart_required: true });
  expect(screen.getByText(/New keys are saved. Restart the engine/)).toBeTruthy();
  expect(screen.getByText('Applies after restart')).toBeTruthy();
  const petRow = screen.getByRole('button', { name: 'Pet food key: f. Change' }).closest('tr')!;
  expect(within(petRow).getByText('Not tested')).toBeTruthy();
  expect(within(petRow).queryByText('Works')).toBeNull();
  fireEvent.click(within(petRow).getByRole('button', { name: 'Go to the control tests' }));
  expect(onTest).toHaveBeenCalled();
});

it('explains the engine refusal in its own words', async () => {
  const command = vi.fn(async () => { throw new Error('F is used for both HP potion and Pet food'); });
  const s = snapshot({ probes: {}, key_settings: { active, saved: active, restart_required: false, editable: true, supported } });
  render(<KeySettings snapshot={s} client={{ command } as unknown as EngineClient} disabled={false} onTest={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'HP potion key: insert. Change' }));
  fireEvent.keyDown(window, { key: 'f' });
  fireEvent.click(screen.getByRole('button', { name: 'Save keys' }));
  expect(await screen.findByText('F is used for both HP potion and Pet food')).toBeTruthy();
});
