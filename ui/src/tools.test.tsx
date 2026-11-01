import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EngineClient } from './client';
import { DiagnosticsTool, PotionsTool, SettingsTool, TrackingTool } from './tools';
import type { ToolProps } from './tools';
import { snapshot } from './test-fixtures';

afterEach(() => cleanup());

function setup(changes: Partial<ToolProps> = {}) {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockImplementation(async name => {
    if (name === 'windows') return [{ hwnd: 4, title: 'MapleStory', client: { x: 0, y: 0, width: 1024, height: 768 }, focused: false, dpi: 96 }];
    return { ok: true };
  });
  const props: ToolProps = {
    snapshot: snapshot({ capture_only: false, readiness: {
      preview: { ready: true, reason: '' }, combat: { ready: true, reason: '' }, potions: { ready: true, reason: '' },
    } }), client, act: async operation => { await operation(); }, disabled: false,
    selected: () => ({ id: 'frozen', x: 10, y: 20, width: 30, height: 40 }), clear: vi.fn(),
    runMode: 'preview', setRunMode: vi.fn(), ...changes,
  };
  return { command, props };
}

it('teaches each selected example and reloads the catalog with original frozen coordinates', async () => {
  const { command, props } = setup();
  render(<TrackingTool {...props} />);
  for (const [label, kind] of [['Add player', 'player'], ['Add name tag', 'nametag'], ['Add monster', 'monster']]) {
    fireEvent.click(screen.getByRole('button', { name: label }));
    await waitFor(() => expect(command).toHaveBeenCalledWith('template', { id: 'frozen', x: 10, y: 20, width: 30, height: 40, kind }));
  }
  fireEvent.click(screen.getByRole('button', { name: 'Reload templates' }));
  expect(command).toHaveBeenCalledWith('reload_templates');
});

it('retains potion settings, calibration and all three mode controls', async () => {
  const { command, props } = setup();
  render(<PotionsTool {...props} />);
  fireEvent.change(screen.getByLabelText('HP threshold (%)'), { target: { value: '45' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save thresholds' }));
  expect(command).toHaveBeenCalledWith('autopotter_settings', { hp_threshold: 45, mp_threshold: 30, cooldown: 1.5 });
  for (const [label, name] of [['Start potion preview', 'autopotter_start'], ['Start live potions', 'autopotter_live'], ['Stop potions', 'autopotter_stop']]) {
    fireEvent.click(screen.getByRole('button', { name: label }));
    expect(command).toHaveBeenCalledWith(name);
  }
  for (const resource of ['hp', 'mp']) {
    fireEvent.click(screen.getByRole('button', { name: `Calibrate ${resource.toUpperCase()} bar` }));
    expect(command).toHaveBeenCalledWith('autopotter_calibrate', { id: 'frozen', x: 10, y: 20, width: 30, height: 40, resource });
  }
});

it('retains connection, crop, recording and each individual probe command', async () => {
  const { command, props } = setup();
  render(<SettingsTool {...props} />);
  await waitFor(() => expect(screen.getByRole('option', { name: /MapleStory · 1024/ })).toBeTruthy());
  for (const [label, name] of [['Reconnect saved game', 'connect_saved_window'], ['Reset crop', 'reset_crop'], ['Confirm game view manually', 'confirm_capture'], ['Start full recording', 'record']]) {
    fireEvent.click(screen.getByRole('button', { name: label }));
    await waitFor(() => expect(command.mock.calls.some(([actual]) => actual === name)).toBe(true));
  }
  fireEvent.click(screen.getByRole('button', { name: 'Attach window' }));
  expect(command).toHaveBeenCalledWith('attach', { hwnd: 4 });
  fireEvent.click(screen.getByRole('button', { name: 'Apply selected crop' }));
  expect(command).toHaveBeenCalledWith('crop', { id: 'frozen', x: 10, y: 20, width: 30, height: 40 });
  fireEvent.change(screen.getByLabelText('x'), { target: { value: '-1920' } });
  fireEvent.click(screen.getByRole('button', { name: 'Capture manual region' }));
  expect(command).toHaveBeenCalledWith('manual', { x: -1920, y: 0, width: 1366, height: 768 });
  for (const action of [...props.snapshot.required_probes, ...props.snapshot.optional_probes]) {
    fireEvent.click(screen.getByRole('button', { name: action.replaceAll('_', ' ') }));
    expect(command).toHaveBeenCalledWith('probe', { action });
  }
  expect(screen.getByRole('link', { name: /legacy debugger/ }).getAttribute('href')).toBe('/legacy');
});

it('confirmation and rejection carry the displayed probe identity and generation', async () => {
  const { command, props } = setup();
  props.snapshot.active_probe = { id: 7, generation: 12, action: 'attack', phase: 'awaiting_confirmation', instruction: 'Confirm one observed attack' };
  render(<SettingsTool {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm observed effect' }));
  expect(command).toHaveBeenCalledWith('confirm_probe', { id: 7, generation: 12 });
  fireEvent.click(screen.getByRole('button', { name: 'Reject probe' }));
  expect(command).toHaveBeenCalledWith('reject_probe', { id: 7, generation: 12 });
});

it('names the blocker and disables probes while recognition lags', () => {
  const { command, props } = setup();
  props.snapshot.readiness.preview = { ready: false, reason: 'Recognition is 4.2 s behind the game picture (limit 1.5 s)' };
  render(<SettingsTool {...props} />);
  expect(screen.getByText(/Probes blocked: Recognition is 4.2 s behind/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'left' }));
  expect(screen.getByRole('button', { name: 'left' }).hasAttribute('disabled')).toBe(true);
  expect(command).not.toHaveBeenCalledWith('probe', { action: 'left' });
});

it('capture-only keeps probe buttons disabled and diagnostics retain worker recovery', async () => {
  const { props } = setup({ snapshot: snapshot() });
  const { unmount } = render(<SettingsTool {...props} />);
  expect(screen.getByRole('button', { name: 'attack' }).hasAttribute('disabled')).toBe(true);
  unmount();
  const { command, props: diagnostics } = setup();
  render(<DiagnosticsTool {...diagnostics} />);
  fireEvent.click(screen.getByRole('button', { name: 'Restart capture worker' }));
  expect(command).toHaveBeenCalledWith('restart_capture');
});

it('requires explicit pose identity and outfit, starts and stops collection', async () => {
  const poses = { enabled: false, identity: '', outfit: '', identities: ['alice', 'bob'], saved: 0, duplicates: 0, rejected: 0, pending: 0, limit: 32, reason: 'Off' };
  const { command, props } = setup({ snapshot: snapshot({ pose_collection: poses }) });
  const view = render(<TrackingTool {...props} />);
  expect((screen.getByRole('button', { name: 'Start pose collection' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Pose character'), { target: { value: 'alice' } });
  fireEvent.change(screen.getByLabelText('Pose outfit'), { target: { value: 'winter' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start pose collection' }));
  await waitFor(() => expect(command).toHaveBeenCalledWith('pose_collection', { enabled: true, identity: 'alice', outfit: 'winter' }));
  view.rerender(<TrackingTool {...props} snapshot={snapshot({ pose_collection: { ...poses, enabled: true, identity: 'alice', outfit: 'winter' } })} />);
  expect((screen.getByLabelText('Pose character') as HTMLSelectElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Stop pose collection' }));
  expect(command).toHaveBeenCalledWith('pose_collection', { enabled: false });
  view.rerender(<TrackingTool {...props} snapshot={snapshot({ pose_collection: poses })} />);
  fireEvent.change(screen.getByLabelText('Pose character'), { target: { value: 'bob' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start pose collection' }));
  expect(command).toHaveBeenCalledWith('pose_collection', { enabled: true, identity: 'bob', outfit: 'winter' });
});
