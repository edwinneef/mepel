import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { AreaProfile, Snapshot } from './contracts';
import type { OverlayAction, OverlayClient } from './overlay';
import type { DashboardSession } from './dashboard';
import type { ToolProps } from './tools';
import type { FarmingRoute } from './PathBuilder';
import type { ViewImage } from './useViewport';
import { SettingsTool, TrackingTool, PotionsTool, DiagnosticsTool } from './tools';
import { BowmanSetup, WeaponRange } from './BowmanSetup';
import { PlayerCapture } from './PlayerCapture';
import { CombatResults } from './CombatResults';
import { GoBar } from './GoBar';
import { MapTab } from './MapTab';
import { PositionPanel } from './PositionPanel';
import { AlarmBanner } from './AlarmBanner';
import { Facts, Journal, SpotMap } from './DashboardParts';
import { batchReport } from './batch';
import type { BatchState } from './batch';
import { CheckList, LayerToggles, LengthPicker, LoopChooser, Meter, NextCheck, PlanPicker, StateBadge } from './ClearParts';
import { firstBlocker, PLANS, startChecks, statusSentence } from './vocabulary';
import { KeySettings } from './KeySettings';
import { displayKey } from './ClearParts';
import type { BotState, LayerId, Plan } from './vocabulary';

export type Page = 'run' | 'setup' | 'maps' | 'history';
type SetupSection = 'start' | 'keys' | 'connection' | 'recognition' | 'potions';
const PAGES: { id: Page; label: string }[] = [
  { id: 'run', label: 'Run' }, { id: 'setup', label: 'Set up' }, { id: 'maps', label: 'Maps' }, { id: 'history', label: 'History' },
];
const SETUP: { id: SetupSection; label: string }[] = [
  { id: 'start', label: 'Before you start' }, { id: 'keys', label: 'Keys' }, { id: 'connection', label: 'Connection' },
  { id: 'recognition', label: 'Recognition' }, { id: 'potions', label: 'Potions' },
];
/** Pages that edit setup. Opening one stops the bot, as the old settings tabs did. */
export const PANEL_PAGES: Page[] = ['setup', 'maps'];

export interface ClearDashboardProps {
  s: Snapshot | null; client: OverlayClient; dashboard: DashboardSession; toolProps: ToolProps | null;
  connected: boolean; disabled: boolean; builderDisabled: boolean; notice: string; error: string;
  state: BotState; running: boolean; starting: boolean; canTurnOn: boolean; reason: string | undefined;
  action: OverlayAction; setAction(action: OverlayAction): void; toggle(): void; stop(): void;
  page: Page; setPage(page: Page): void;
  layers: Record<LayerId, boolean>; toggleLayer(id: LayerId): void;
  game: ReactNode; frozen: boolean; image: ViewImage | null; freeze(): void; live(): void;
  map: AreaProfile | null; areas: { id: string; name: string; revision: number }[]; refreshAreas(): Promise<void>;
  routes: FarmingRoute[] | undefined; record(): void; recordingFull: boolean; recordLeft: number | null | undefined;
  act(fn: () => Promise<unknown>): Promise<void>;
  batch: BatchState;
}

const DEFAULT_LABEL = 'Decision preview';

/** The action a plan starts. Saved loop and One platform run as the in-game overlay's guarded batch (see OverlayApp). */
export function planAction(plan: Plan, minutes: number, loop: FarmingRoute | null): OverlayAction {
  if (plan === 'loop' && loop) return {
    name: 'batch', label: `${PLANS.loop.short}: ${loop.name} · ${minutes} min`,
    payload: { kind: 'learn', circuit: { id: loop.id, revision: loop.revision }, minutes },
  };
  if (plan === 'platform') return { name: 'batch', label: `${PLANS.platform.short} · ${minutes} min`, payload: { kind: 'single', minutes } };
  return { name: 'dry_run', label: PLANS.watch.title, payload: {} };
}

export function ClearDashboard(p: ClearDashboardProps) {
  const { s, client, toolProps } = p;
  const [plan, setPlan] = useState<Plan>('watch');
  const [minutes, setMinutes] = useState(15);
  const [loopId, setLoopId] = useState<string | null>(null);
  const [section, setSection] = useState<SetupSection>('start');
  const loops = useMemo(() => p.routes?.filter(route => route.loop), [p.routes]);
  const loop = loops?.find(route => route.id === loopId) ?? loops?.[0] ?? null;
  const wanted = planAction(plan, minutes, loop);
  const wantedKey = JSON.stringify(wanted);
  const lastPlan = useRef('');
  // A plan choice (or the engine resetting to its default) selects the plan's action. Anything a
  // Set up tool selects (a control probe, potions only) stays selected until a plan is picked again.
  useEffect(() => {
    const reset = p.action.name === 'dry_run' && p.action.label === DEFAULT_LABEL;
    if (lastPlan.current !== wantedKey || reset) {
      lastPlan.current = wantedKey;
      if (JSON.stringify(p.action) !== wantedKey) p.setAction(wanted);
    }
  });
  const custom = JSON.stringify(p.action) !== wantedKey;
  const checks = startChecks(s, { connected: p.connected, plan, loops: plan === 'loop' ? loops?.length : undefined });
  const blocker = custom ? null : firstBlocker(checks);
  const busy = p.running || p.starting;
  const canStart = !busy && p.canTurnOn && !blocker && !(plan === 'loop' && !loop && !custom);
  const sentence = custom && p.state === 'off'
    ? { headline: p.canTurnOn ? `Ready: ${p.action.label}` : `Can't start ${p.action.label}`, detail: p.reason ?? '' }
    : statusSentence(p.state, blocker, { plan, loop: loop?.name, minutes, reason: p.running ? p.reason : undefined });
  const locked = s?.capture_only ? 'Capture-only session: game keys are locked.' : undefined;
  const focus = () => void p.act(() => client.command('focus_game'));
  const potion = s?.autopotter;
  const recordLabel = p.recordingFull ? `Stop recording${p.recordLeft == null ? '' : ` · ${Math.ceil(p.recordLeft)} s left`}` : 'Record 30 s';
  const choose = (name: string, label: string) => p.setAction({ name, label, payload: {} });
  const stopKey = displayKey(String(s?.key_settings?.active.emergency_key ?? 'f8'));

  return <div className="clear clear-dashboard">
    <header className="c-bar">
      <span className="c-logo"><i aria-hidden="true" />Maple Bot</span>
      <nav className="c-tabs" aria-label="Dashboard pages">
        {PAGES.map(page => <button key={page.id} className="c-opt" aria-current={p.page === page.id ? 'page' : undefined}
          onClick={() => p.setPage(page.id)}>{page.label}</button>)}
      </nav>
      <span className="c-session">{!s ? 'Waiting for the engine' : s.capture_only ? 'Capture only · game keys locked' : 'Input-capable session'}</span>
    </header>

    <section className="c-hero" aria-live="polite">
      <div><StateBadge state={p.state} /><h1>{sentence.headline}</h1>{sentence.detail && <p>{sentence.detail}</p>}</div>
      <button className="c-btn stop c-hero-stop" onClick={p.stop}>Stop<kbd>{stopKey}</kbd></button>
    </section>

    {p.dashboard.disconnected && <section className="c-banner bad" role="alert" aria-label="Dashboard controls disconnected">
      <h2>Dashboard controls are disconnected</h2>
      <p>{p.dashboard.connectionIssue}</p>
      <p>Saved-path editing stays available while the engine is connected and the bot is Off.</p>
      <p>Connecting the MapleStory window supplies the picture; it does not reconnect dashboard controls.
        Close any other dashboard or overlay that owns controls, then reload this page. The bot stays Off.</p>
    </section>}
    {s && <AlarmBanner snapshot={s} onAcknowledge={id => void p.act(() => client.command('acknowledge', { incident_id: id }))} />}
    {p.error && <p className="c-banner warn" role="alert">{p.error}</p>}
    {p.notice && !p.error && <p className="c-notice" role="status">{p.notice}</p>}
    {PANEL_PAGES.includes(p.page) && <p className="c-notice">The bot is Off while {p.page === 'maps' ? 'Maps' : 'Set up'} is open. Start returns to Run.</p>}

    {p.page === 'run' && <>
      <div className="c-run">
        <section className="c-card" aria-labelledby="c-checks-title"><h2 id="c-checks-title">Before you start</h2>
          <CheckList checks={checks} onAction={focus} disabled={p.disabled} /></section>
        <section className="c-card c-stage" aria-label="Dashboard game view">
          {p.game}
          <div className="c-under">
            <Meter label="HP" kind="hp" percent={potion?.readings.hp?.percent} threshold={potion?.settings.hp_threshold ?? 50} />
            <Meter label="MP" kind="mp" percent={potion?.readings.mp?.percent} threshold={potion?.settings.mp_threshold ?? 50} />
            <LayerToggles values={p.layers} onToggle={p.toggleLayer} />
            <button className="c-btn small" disabled={p.disabled} onClick={p.record}>{recordLabel}</button>
          </div>
        </section>
        <section className="c-card c-plan" aria-label="Start a run">
          {custom ? <>
            <h2>Selected in Set up</h2>
            <p className="c-selected">{p.action.label}</p>
            <button className="c-btn small" disabled={busy} onClick={() => { lastPlan.current = ''; p.setAction(wanted); }}>Back to the plans</button>
          </> : <>
            <h2>What should it do?</h2>
            <PlanPicker plan={plan} onPlan={setPlan} disabled={busy} available={{ loop: locked, platform: locked }} />
            <div className="c-field"><span>Loop</span>
              <LoopChooser plan={plan} loops={loops?.map(route => ({ id: route.id, name: route.name, stops: route.stops.length }))}
                selected={loop?.id ?? null} onSelect={setLoopId} disabled={busy} /></div>
            <div className="c-field"><span>Length</span><LengthPicker plan={plan} minutes={minutes} onMinutes={setMinutes} disabled={busy} /></div>
          </>}
          {busy ? <button className="c-btn start stop" onClick={p.stop}>Stop<kbd>{stopKey}</kbd></button>
            : <button className="c-btn start" disabled={!canStart} title={blocker?.fix || p.reason} onClick={p.toggle}>Start</button>}
          {!busy && (custom ? !p.canTurnOn && p.reason && <p className="c-next bad">{p.reason}</p>
            : <NextCheck blocker={blocker} onAction={focus} disabled={p.disabled} />)}
          {!custom && !busy && <details className="c-more"><summary>Other activities</summary>
            <div className="c-more-row">
              <button className="c-btn small" disabled={Boolean(locked)} onClick={() => choose('autopotter_live', 'Potions only')}>Potions only</button>
              <button className="c-btn small" disabled={Boolean(locked)} onClick={() => choose('arm', 'Combat on this screen, no loop')}>Combat without a loop</button>
            </div></details>}
        </section>
      </div>
      <div className="c-row3">
        <section className="c-card"><h2>Right now</h2><Facts snapshot={s} /></section>
        <section className="c-card"><h2>Last run</h2><LastRun s={s} batch={p.batch} /></section>
        <section className="c-card"><h2>What happened</h2><Journal history={s?.history} /></section>
      </div>
    </>}

    {p.page === 'setup' && <div className="c-setup">
      <nav className="c-subnav" aria-label="Set up sections">
        {SETUP.map(item => <button key={item.id} className="c-opt" aria-current={section === item.id ? 'page' : undefined}
          onClick={() => setSection(item.id)}>{item.label}</button>)}
      </nav>
      <div className="c-setup-body c-tool">
        {section === 'start' && <>
          <section className="c-card"><h2>Before you start</h2><CheckList checks={checks} onAction={focus} disabled={p.disabled} /></section>
          {toolProps && <section className="c-card"><h2>Your character</h2>
            <BowmanSetup {...toolProps} onSetup={tab => setSection(tab === 'Recognition' ? 'recognition' : tab === 'Potions' ? 'potions' : 'connection')} />
            {s && <PlayerCapture snapshot={s} client={client} act={p.act} disabled={p.disabled} />}
            <WeaponRange {...toolProps} /></section>}
        </>}
        {section === 'keys' && s && <KeySettings snapshot={s} client={client} disabled={p.disabled || p.running || p.starting}
          onTest={() => setSection('start')} />}
        {section === 'connection' && <section className="c-card"><h2>Connection</h2>
          <details><summary>Calibration picture and selection</summary>
            <button className="c-btn small" disabled={p.disabled} onClick={p.frozen ? p.live : p.freeze}>{p.frozen ? 'Return to live view' : 'Freeze for selection'}</button>
          </details>
          {toolProps && <SettingsTool {...toolProps} />}</section>}
        {section === 'recognition' && toolProps && <section className="c-card"><h2>Recognition</h2><TrackingTool {...toolProps} /></section>}
        {section === 'potions' && toolProps && <section className="c-card"><h2>Potions</h2><PotionsTool {...toolProps} /></section>}
      </div>
    </div>}

    {p.page === 'maps' && <div className="c-maps c-tool">
      <section className="c-card c-maps-builder"><h2>Path builder</h2>
        {toolProps && <MapTab snapshot={toolProps.snapshot} client={client} disabled={p.disabled} builderDisabled={p.builderDisabled}
          onCircuit={route => { if (route) { setPlan('loop'); setLoopId(route.id); p.setPage('run'); } }} />}</section>
      <div className="c-maps-side">
        <section className="c-card"><h2>{p.map?.name ?? 'This map'}</h2><SpotMap map={p.map} snapshot={s} /></section>
        {s && <section className="c-card"><h2>Go to a place</h2>
          <GoBar snapshot={s} client={client} act={p.act} disabled={p.disabled} availableAreas={p.areas} selectOnly /></section>}
        {toolProps && <details className="c-card" open={!toolProps.snapshot.position?.area_id}><summary>Map tracking</summary>
          <PositionPanel {...toolProps} image={p.frozen ? null : p.image} areas={p.areas} refreshAreas={p.refreshAreas} /></details>}
      </div>
    </div>}

    {p.page === 'history' && <div className="c-history c-tool">
      <section className="c-card"><h2>Last run</h2><LastRun s={s} batch={p.batch} /></section>
      <section className="c-card c-span2"><h2>What happened</h2><Journal history={s?.history} /></section>
      <section className="c-card c-span3"><h2>Combat and potion evidence</h2><CombatResults evidence={s?.combat_evidence} potions={s?.potion_evidence} /></section>
      {toolProps && <details className="c-card c-span3"><summary>Diagnostics</summary><DiagnosticsTool {...toolProps} /></details>}
      <section className="c-card c-span3 c-session-card"><h2>This dashboard</h2>
        <p className="c-quiet">{!s ? 'Waiting for the engine.' : s.capture_only ? 'Capture-only session. Game keys are locked.' : 'Input-capable session. Existing safety checks apply.'}</p>
        <button className="c-btn" onClick={() => void p.act(() => p.dashboard.quit())}>Disconnect dashboard</button></section>
    </div>}
  </div>;
}

/** The last batch result in plain words, else the engine's last stop. */
function LastRun({ s, batch }: { s: Snapshot | null; batch: BatchState }) {
  if (batch.running || batch.pending) return <div className="c-result" data-tone="info">
    <b>{batch.pending ? 'Waiting for the in-game overlay to start it' : 'Running'}</b>
    {batch.line && <p className="c-quiet">{batch.line}</p>}</div>;
  const report = batchReport(batch);
  if (report) return <div className="c-result" data-tone={report.tone}><b>{report.headline}</b>
    {report.detail && <p className="c-pre">{report.detail}</p>}</div>;
  return <LastStop s={s} />;
}

function LastStop({ s }: { s: Snapshot | null }) {
  const stop = s?.stop;
  if (!stop) return <p className="c-quiet">Nothing has stopped in this session yet.</p>;
  return <div className="c-result" data-tone={stop.severity === 'info' ? 'info' : 'fail'}>
    <b>{stop.message}</b>
    <p className="c-quiet">{new Date(stop.time * 1000).toLocaleTimeString()} · {stop.code}</p>
    {stop.clip_path && <p className="c-clip">Clip: <code>{stop.clip_path}</code></p>}
  </div>;
}
