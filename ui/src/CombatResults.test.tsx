import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CombatResults } from './CombatResults';
import type { PotionRecord } from './potionEvidence';
import { OverlayApp } from './OverlayApp';
import { OverlayClient } from './overlay';
import { json, snapshot } from './test-fixtures';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); delete window.mapleOverlay; });

function potion(overrides: Partial<PotionRecord> = {}): PotionRecord {
  return { id: 'session:7', session_id: 'session', ticket: 7, resource: 'hp',
    recording: 'session-potion-hp-t7', status: 'observed_bar_gain', baseline_usable: true,
    before: { frame: 'before.png', sequence: 1, captured_at: 100, capture_clock: 1, percent: 25, confidence: 1 },
    after: { frame: 'after.png', sequence: 2, captured_at: 100.4, capture_clock: 1.4, percent: 60, confidence: 1 },
    outcome: { result: 'hp_potion completed', finished_at: 1.2 }, ...overrides };
}

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

it('shows both pending resources without requesting another probe or changing accepted observations', () => {
  render(<CombatResults evidence={null} potions={{ enabled: true, records: [] }} />);
  expect(screen.getByText('HP: Pending · no retained potion observation')).toBeTruthy();
  expect(screen.getByText('MP: Pending · no retained potion observation')).toBeTruthy();
  expect(screen.getByText(/Previously accepted observations remain unchanged/)).toBeTruthy();
  expect(screen.queryByText(/Select a probe/)).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
});

it('shows the latest HP and MP observations separately even with no retained combat run', () => {
  render(<CombatResults evidence={null} potions={{ enabled: true, records: [
    potion({ status: 'superseded' }), potion({ ticket: 8, resource: 'mp', status: 'no_observed_gain' }),
    potion({ ticket: 9 }),
  ] }} />);
  expect(screen.getByText('HP: Bar gain observed · potion recovery unverified')).toBeTruthy();
  expect(screen.getByText('MP: No bar gain observed · potion recovery unverified')).toBeTruthy();
  expect(screen.getByText('HP observation details · ticket 9')).toBeTruthy();
  expect(screen.getByText('MP observation details · ticket 8')).toBeTruthy();
  expect(screen.queryByText(/ticket 7/)).toBeNull();
  expect(screen.getByText(/may precede this run/)).toBeTruthy();
  expect(screen.getAllByText('25.0% → 60.0%')).toHaveLength(2);
  expect(screen.getAllByText(/does not verify that both PNGs reached disk/)).toHaveLength(2);
  expect(screen.getByText(/no gain does not prove potion failure/)).toBeTruthy();
});

it.each([
  ['queued', 'Pending · potion input queued'],
  ['awaiting_observation', 'Pending · waiting for a fresh bar reading'],
  ['baseline_unavailable', 'Incomplete · no usable before reading'],
  ['observation_unavailable', 'Incomplete · no usable after reading'],
  ['input_not_completed', 'Incomplete · potion input did not complete'],
  ['outcome_unavailable', 'Incomplete · input outcome unavailable'],
  ['source_changed', 'Incomplete · capture view changed'],
  ['superseded', 'Incomplete · another potion replaced this observation'],
  ['capture_ended', 'Incomplete · capture ended before observation finished'],
  ['future_status', 'Incomplete · observation status unavailable'],
])('keeps %s incomplete or pending rather than reporting success or failure', (status, label) => {
  render(<CombatResults evidence={null} potions={{ enabled: false, records: [
    potion({ status, baseline_usable: false, after: null, outcome: null }),
  ] }} />);
  expect(screen.getByText(`HP: ${label}`)).toBeTruthy();
  expect(screen.getByText(/Passive collection disabled/)).toBeTruthy();
  expect(screen.queryByText('25.0% → 60.0%')).toBeNull();
});

it('distinguishes an older engine without passive evidence support', () => {
  render(<CombatResults evidence={null} />);
  expect(screen.getByText(/Passive evidence unavailable from this engine/)).toBeTruthy();
  expect(screen.getByText(/HP\/MP recovery and basic-attack fallback remain unverified/)).toBeTruthy();
});

it('exports the original run fields together with all retained passive tickets', async () => {
  let saved: Blob | undefined;
  vi.stubGlobal('URL', { createObjectURL: vi.fn((blob: Blob) => { saved = blob; return 'blob:export'; }), revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const records = [potion(), potion({ ticket: 8, resource: 'mp' })];
  render(<CombatResults evidence={{ session_id: 'session', run: 3, activity: 'combat',
    started_at: 100, stop_reason: 'F8 pressed', hit_confirmed: null, events: [] }}
    potions={{ enabled: true, records }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Save run evidence' }));
  const text = await new Promise<string>(resolve => {
    const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(saved!);
  });
  expect(JSON.parse(text)).toMatchObject({ run: 3, stop_reason: 'F8 pressed', hit_confirmed: null,
    potion_evidence: { enabled: true, records } });
});

it('wires passive evidence from engine status into the Bot panel without gameplay commands', async () => {
  const commands: string[] = [];
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, options) => {
    if (String(url).startsWith('/api/v1/frame')) return new Response(new Blob(['image']));
    if (url === '/api/v1/status') return json(snapshot({ potion_evidence: { enabled: true, records: [potion()] } }));
    const command = JSON.parse(String(options?.body)); commands.push(command.name);
    return json(command.name === 'area_list' ? { areas: [] } : { ok: true });
  });
  vi.stubGlobal('fetch', fetcher);
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:frame'), revokeObjectURL: vi.fn() });
  window.mapleOverlay = { settings: vi.fn(), quit: vi.fn(), heartbeat: vi.fn(),
    subscribe: callback => { callback({ type: 'panel', value: true }); return () => {}; } };
  render(<OverlayApp client={new OverlayClient('token', fetcher)} />);
  await waitFor(() => expect(screen.getByText('HP: Bar gain observed · potion recovery unverified')).toBeTruthy());
  expect(screen.getByText('BOT OFF')).toBeTruthy();
  expect(commands).toEqual(['area_list']);
});
