import { PlayerCapture } from './PlayerCapture';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { OverlayClient, freshDetections, isRunning, positionLearning } from './overlay';
import type { OverlayAction } from './overlay';
import type { AreaProfile, Rect } from './contracts';
import { LiveDetectionBoxes } from './LiveDetectionBoxes';
import { useDrawings } from './useDrawings';
import { useOverlayLayout } from './overlayLayout';
import { useViewport } from './useViewport';
import { GameViewport } from './GameViewport';
import { SettingsTool, TrackingTool, PotionsTool, DiagnosticsTool } from './tools';
import { PositionPanel } from './PositionPanel';
import { GoBar } from './GoBar';
import { NavigationPanel } from './NavigationPanel';
import { MapTab } from './MapTab';
import type { FarmingRoute } from './PathBuilder';
import { AlarmBanner } from './AlarmBanner';
import { SavedTerrainOverlay } from './SavedTerrainOverlay';
import { OverlayMenu, type BatchState, type PathAvailability } from './OverlayMenu';
import { BowmanSetup, WeaponRange } from './BowmanSetup';
import { CombatResults } from './CombatResults';
import { AttackRangeOverlay } from './AttackRangeOverlay';
import type { DashboardSession } from './dashboard';
import { Facts, Gauge, Journal, NavIcon, SpotMap } from './DashboardParts';
import './overlay.css';
import './dashboard.css';

export function OverlayApp({ client, dashboard, outlinesOnly = false }: {
  client: OverlayClient; dashboard?: DashboardSession; outlinesOnly?: boolean;
}) {
  const host = dashboard ?? window.mapleOverlay;
  const state = useSyncExternalStore(client.subscribe, client.getState);
  const s = state.snapshot;
  const [panel, setPanel] = useState(Boolean(dashboard));
  const [gameBounds, setGameBounds] = useState<(Rect & { visible: boolean }) | null>(null);
  const layout = useOverlayLayout(panel && !dashboard);
  const [tab, setTab] = useState('Bot');
  const [layers, setLayers] = useState(true);
  const [widget, setWidget] = useState(true);
  const [terrain, setTerrain] = useState(true);
  const [attackRange, setAttackRange] = useState(true);
  const [action, setAction] = useState<OverlayAction>({ name: 'dry_run', payload: {}, label: 'Decision preview' });
  const [now, setNow] = useState(Date.now());
  const [map, setMap] = useState<AreaProfile | null>(null);
  const [areas, setAreas] = useState<{ id: string; name: string; revision: number }[]>([]);
  const [starting, setStarting] = useState(false);
  const [controllerReady, setControllerReady] = useState(!window.mapleOverlay?.companion);
  const [supervised, setSupervised] = useState(false);
  const [batch, setBatch] = useState<BatchState>({ running: false });
  const startRef = useRef(false);
  const wasRunning = useRef(false);
  const dataKey = useRef('');
  const dataRetryAfter = useRef(0);
  const currentToggle = useRef<() => void>(() => {});
  const view = useViewport(client, s, state.connected && (panel || Boolean(dashboard)), Boolean(dashboard && layers));
  const running = isRunning(s);
  // Status can arrive between timer ticks; don't compare a new frame against
  // the previous tick and incorrectly classify it as coming from the future.
  const fresh = freshDetections(s, state.connected, Math.max(now, Date.now()));
  const fastDrawing = useDrawings(state.connected, s?.session_id);
  const drawing = fastDrawing === undefined ? (s?.live_detections === undefined ? s : s.live_detections) : fastDrawing;
  const drawingFresh = freshDetections(drawing, state.connected, Math.max(now, Date.now()))
    && (!fastDrawing || Date.now() - (fastDrawing.frame.captured_at ?? 0) * 1000 <= 500);
  const disabled = !state.connected || state.busy || state.needsReload || Boolean(dashboard?.disconnected);
  const builderDisabled = !state.connected || state.busy || state.needsReload;
  // In-game widget: saved paths for the player's map. The engine refuses route reads during
  // gameplay, so read only while Off, keep the last answer meanwhile, and re-read every 30 s
  // so a path saved in the dashboard appears.
  const pathArea = outlinesOnly && !dashboard && state.connected ? s?.position?.area_id ?? null : null;
  const [paths, setPaths] = useState<PathAvailability>({ state: 'unknown' });
  const pathRead = useRef({ key: '', area: '' });
  const pathKey = pathArea && !running ? `${pathArea}:${Math.floor(now / 30000)}` : '';
  useEffect(() => {
    if (!pathArea) { pathRead.current = { key: '', area: '' }; setPaths({ state: 'unknown' }); return; }
    if (!pathKey || pathRead.current.key === pathKey) return;
    const newArea = pathRead.current.area !== pathArea;
    pathRead.current = { key: pathKey, area: pathArea };
    if (newArea) setPaths({ state: 'loading' });
    // An answer stays valid for its map even if gameplay started meanwhile; drop it only
    // when the player has moved to another map.
    const area = pathArea;
    void client.command<{ routes?: FarmingRoute[] }>('farm_route_list', { area_id: area })
      .then(value => { if (pathRead.current.area === area) setPaths({ state: 'ready', names: (value.routes ?? []).map(route => route.name), routes: value.routes ?? [] }); })
      .catch(error => {
        if (pathRead.current.area !== area) return;
        pathRead.current.key = '';
        if (newArea) setPaths({ state: 'error', message: error instanceof Error ? error.message : String(error) });
      });
  }, [pathArea, pathKey, client]);
  const readinessKey = action.name === 'probe' ? `probe:${action.payload.action}`
    : action.name === 'arm' ? 'combat' : action.name === 'autopotter_live' ? 'potions' : 'preview';
  const selectedGate = s?.readiness[readinessKey];
  const act = async (fn: () => Promise<unknown>) => { try { await fn(); } catch (e) { client.fail(e); } };
  useEffect(() => {
    const previous = wasRunning.current;
    wasRunning.current = running;
    if (previous && !running && state.connected) client.message(`Off · ${s?.reason ?? 'Engine stopped'}`);
    else if (!previous && running) client.message(`${action.label} On${action.name === 'dry_run' ? ' · no gameplay keys' : ''}`);
  }, [running, state.connected, client, s?.reason, action.label, action.name]);
  const refreshAreas = async () => {
    const result = await client.command<{ areas: { id: string; name: string; revision: number }[] }>('area_list');
    setAreas(result.areas);
  };
  useEffect(() => client.start(), [client]);
  useEffect(() => dashboard?.connect(client), [client, dashboard]);
  useEffect(() => { client.select = setAction; return () => { client.select = () => {}; }; }, [client]);
  useEffect(() => {
    const timer = setInterval(() => { setNow(Date.now()); host?.heartbeat(); }, 200);
    const unsub = host?.subscribe(event => {
      if (event.type === 'panel') setPanel(Boolean(event.value));
      if (event.type === 'game-bounds') setGameBounds(event.value as (Rect & { visible: boolean }) | null);
      if (event.type === 'toggle') currentToggle.current();
      if (event.type === 'off') { startRef.current = false; setStarting(false); void act(() => client.command('stop')); }
      if (event.type === 'layers') setLayers(value => !value);
      if (event.type === 'widget') setWidget(value => !value);
      if (event.type === 'error') client.fail(event.value);
      if (event.type === 'batch') setBatch(event.value as BatchState);
      if (event.type === 'controller') setControllerReady(event.value === true);
    });
    return () => { clearInterval(timer); unsub?.(); };
  }, [client, host]);
  useEffect(() => {
    setAction({ name: 'dry_run', payload: {}, label: 'Decision preview' });
    setMap(null);
  }, [s?.session_id]);
  useEffect(() => {
    if (!s || !state.connected || state.busy) return;
    const key = `${s.session_id}:${s.position?.area_id}:${s.position?.teaching?.map_revision}`;
    if (key === dataKey.current || Date.now() < dataRetryAfter.current) return;
    dataKey.current = key;
    setMap(null);
    void act(async () => {
      try {
        await refreshAreas();
        if (s.position?.area_id) {
          const value = await client.command<{ profile: AreaProfile }>('area_load', { area_id: s.position.area_id });
          if (dataKey.current === key) setMap(value.profile);
        }
      } catch (error) {
        if (dataKey.current === key) {
          dataKey.current = '';
          dataRetryAfter.current = Date.now() + 1000;
        }
        throw error;
      }
    });
  }, [client, s?.session_id, s?.position?.area_id, s?.position?.teaching?.map_revision, state.connected, state.busy, now]);
  const toggle = async () => {
    if (running || startRef.current) {
      startRef.current = false; setStarting(false);
      await act(() => client.command('stop'));
      client.message('F6 · bot switched Off'); return;
    }
    if (!dashboard && !panel && !s?.focused) { client.message('F6 · focus the game to turn On; F8 always stops'); return; }
    if (disabled || !fresh) { client.message('OFF · waiting for fresh recognition and an engine connection'); return; }
    if (selectedGate?.ready === false) { client.message(selectedGate.reason); return; }
    client.message(`F6 · starting ${action.label}${action.name === 'dry_run' ? ' (no gameplay keys)' : ''}`);
    startRef.current = true; setStarting(true);
    try {
      if (panel || dashboard) await host?.settings(false);
      if (!startRef.current) return;
      await client.execute(action);
      const result = await client.readStatus();
      if (!isRunning(result)) client.message(`${action.label} stopped: ${result.reason}`);
    } catch (e) { client.fail(e); }
    finally { startRef.current = false; setStarting(false); }
  };
  currentToggle.current = () => void toggle();
  useEffect(() => {
    if (!dashboard) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'F8') { event.preventDefault(); startRef.current = false; setStarting(false); void act(() => client.command('stop')); return; }
      if (event.repeat || event.target instanceof Element && event.target.closest('input, select, textarea, [contenteditable=true]')) return;
      if (event.key === 'F6') { event.preventDefault(); currentToggle.current(); }
      if (event.key === 'F7') { event.preventDefault(); void act(() => dashboard.settings(!panel)); }
      if (event.key === 'F9') { event.preventDefault(); setLayers(value => !value); }
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [dashboard, client, panel]);
  const choose = (name: string, label: string) => setAction({ name, label, payload: {} });
  const selectCircuit = (route: FarmingRoute | null) => setAction(route ? {
    name: 'arm',
    label: `${route.name} · revision ${route.revision} · ${route.stops.length} stops · 15 minutes · HP/MP potions`,
    payload: { circuit: { id: route.id, revision: route.revision }, farming: {
      session_minutes: 15, no_consumables: false, pet_recovery: false,
      hp_threshold: 50, mp_threshold: 50,
    } },
  } : { name: 'dry_run', label: 'Decision preview', payload: {} });
  const active = state.connected && fresh && running;
  const status = !state.connected || dashboard?.disconnected ? 'DISCONNECTED' : s?.alarm.active ? 'BLOCKED' : starting ? 'STARTING'
    : active ? (s?.mode.includes('wait') || s?.mode === 'pending_arm' ? 'STARTING' : 'ON') : 'OFF';
  const toolProps = s ? { snapshot: s, client, act, disabled, selected: view.selected, clear: view.clear, selectOnly: true,
    startInstruction: dashboard ? 'Select an activity, click Turn On in the dashboard, then focus the game during the countdown.' : undefined,
    runMode: (action.name === 'arm' ? 'live' : 'preview') as 'live' | 'preview',
    setRunMode: (mode: 'live' | 'preview' | 'navigation') => choose(mode === 'live' ? 'arm' : 'dry_run', mode),
  } : null;
  const game = gameBounds ?? { x: 0, y: 0, width: innerWidth, height: innerHeight };
  const recordingFull = Boolean(s?.recorder?.full);
  const recordLeft = s?.recorder?.full_remaining as number | null | undefined;
  // Keep the analyzed image and its observations together through loading of the
  // next frame. Early drawing packets belong to the native overlay, not this image.
  const analyzed = view.image?.observation;
  const previewDrawing = analyzed && s?.frame.available && view.image && !view.frozen
    && freshDetections(analyzed, state.connected && !state.needsReload && !dashboard?.disconnected, Math.max(now, Date.now()))
    && drawing && drawing.frame.source_id === analyzed.frame.source_id
    && analyzed.frame.source_id === s.frame.source_id && analyzed.frame.source_id === view.image.sourceId
    && analyzed.frame.id === view.image.key ? analyzed : null;
  const drawingLayers = (packet: NonNullable<typeof drawing>, paired = false) => <>
    {terrain && <SavedTerrainOverlay key={packet.frame.source_id} map={map} position={packet.position}
      alignment={paired || fastDrawing === undefined ? undefined : fastDrawing?.terrain ?? null}
      now={paired ? (packet.frame.captured_at ?? 0) * 1000 : Math.max(now, Date.now())} />}
    <LiveDetectionBoxes drawing={packet} />
    {attackRange && <AttackRangeOverlay player={packet.player} setup={s?.attack_setup} threshold={s?.player_threshold} />}
  </>;
  const learning = positionLearning(s?.position, Math.max(now, Date.now()));
  if (outlinesOnly && !dashboard) return <div className="native-overlay">
    {learning && gameBounds?.visible && <div className="overlay-learning" aria-label="Position learning"
      style={{ left: game.x + game.width / 2, top: game.y + 8 }}>{learning}</div>}
    {(layers || attackRange) && drawingFresh && drawing && gameBounds?.visible && <svg className="world-layer"
      style={{ left: game.x, top: game.y, width: game.width, height: game.height }}
      viewBox={`0 0 ${drawing.frame.width} ${drawing.frame.height}`} preserveAspectRatio="none" aria-label="Live detections">
      {layers && <LiveDetectionBoxes drawing={drawing} compact />}
      {attackRange && <AttackRangeOverlay player={drawing.player} setup={s?.attack_setup} threshold={s?.player_threshold} />}
    </svg>}
    {gameBounds && widget && <OverlayMenu s={s ?? null} status={status} game={game}
      layers={layers} attackRange={attackRange} names={terrain}
      setLayers={setLayers} setAttackRange={setAttackRange} setNames={setTerrain}
      batch={batch} canBatch={Boolean(window.mapleOverlay?.batch) && controllerReady} paths={paths}
      startBlocker={window.mapleOverlay?.companion && !controllerReady
        ? 'Open the browser dashboard to enable starting. Stop and F8 remain available.' : undefined}
      onStart={(kind, circuit, minutes) => void act(async () => {
        const area = s?.position?.area_id;
        const launch = window.mapleOverlay?.batch;
        if (!area || !launch) return;
        const result = await launch({ kind, area, ...(circuit ? { circuit, minutes } : {}) });
        if (!result.started) setBatch({ running: false, output: JSON.stringify({ blocked: result.reason }) });
      })}
      capture={s && <PlayerCapture snapshot={s} client={client} act={act} disabled={disabled} />}
      onStop={() => void act(() => client.command('stop'))} />}
    {terrain && map && drawingFresh && drawing && gameBounds?.visible && <svg className="world-layer"
      style={{ left: game.x, top: game.y, width: game.width, height: game.height }}
      viewBox={`0 0 ${drawing.frame.width} ${drawing.frame.height}`} preserveAspectRatio="none">
      {/* Names need no fine alignment: use it when valid, else the position's projection. */}
      <SavedTerrainOverlay map={map} position={drawing.position} compact
        alignment={fastDrawing?.terrain?.alignment.valid ? fastDrawing.terrain : undefined}
        now={Math.max(now, Date.now())} />
    </svg>}
  </div>;
  const record = () => void act(async () => {
    await client.command('record', recordingFull ? {} : { seconds: 30 });
    if (!recordingFull) await host?.settings(false);
  });
  const settingsBody = <>
    <p>Bot is Off while settings are open. Closing settings never resumes it.</p>
    {!dashboard && <p>Drag panel headings anywhere on the desktop, including outside the game. <button onClick={layout.reset}>Reset positions</button></p>}
    {!dashboard && <nav>{['Bot', 'Connection', 'Recognition', 'Potions', 'Map', 'Diagnostics'].map(name =>
      <button key={name} aria-pressed={tab === name} onClick={() => setTab(name)}>{name}</button>)}</nav>}
    {state.error && <p role="alert" className="warning-copy">{state.error}</p>}
    {state.notice && <p role="status">{state.notice}</p>}
    {!dashboard && s && <AlarmBanner snapshot={s} onAcknowledge={id => void act(() => client.command('acknowledge', { incident_id: id }))} />}
    {tab === 'Bot' && <>
      {toolProps && <BowmanSetup {...toolProps} onSetup={setTab} />}
      <label>Activity<select value={!action.payload.circuit && ['dry_run', 'arm', 'autopotter_live'].includes(action.name) ? action.name : 'custom'} onChange={e => choose(e.target.value, e.target.selectedOptions[0].text)}>
        <option value="dry_run">Decision preview</option><option value="arm" disabled={s?.capture_only}>Combat + configured potions</option>
        <option value="autopotter_live" disabled={s?.capture_only}>Potions only</option>
        {(Boolean(action.payload.circuit) || !['dry_run', 'arm', 'autopotter_live'].includes(action.name)) && <option value="custom">{action.label}</option>}
      </select></label>
      <p>{selectedGate?.reason}</p>
      <button className="primary master-toggle" disabled={disabled || (!running && !starting && selectedGate?.ready === false)} onClick={() => void toggle()}>Turn {running || starting ? 'Off' : 'On'} · F6</button>
      <p>On closes settings and starts the existing countdown. Focus the game. F8 always stops. Combat and navigation retain configured potion priority.</p>
      <CombatResults evidence={s?.combat_evidence} potions={s?.potion_evidence} />
      {s && <GoBar snapshot={s} client={client} act={act} disabled={disabled} availableAreas={areas} selectOnly />}
      <button disabled={disabled} onClick={record}>{recordingFull ? `Stop recording${recordLeft == null ? '' : ` · ${Math.ceil(recordLeft)} s left`}` : 'Record 30 s'}</button>
      <label><input type="checkbox" checked={layers} onChange={e => setLayers(e.target.checked)} /> Show detection layers</label>
      <label><input type="checkbox" checked={attackRange} onChange={e => setAttackRange(e.target.checked)} /> Show attack range</label>
      <label><input type="checkbox" checked={terrain} onChange={e => setTerrain(e.target.checked)} /> Show saved terrain and position</label>
      <p>{s?.capture_only ? 'Capture-only session · gameplay input locked' : 'Input-capable session · existing verification gates apply'}</p>
    </>}
    {['Connection', 'Recognition', 'Potions'].includes(tab) && <>
      <details><summary>Calibration picture and selection</summary>
        {!dashboard && <GameViewport image={view.image} frozen={Boolean(view.frozen)} selection={view.selection} onSelection={view.setSelection} />}
        <button disabled={disabled} onClick={() => void act(view.frozen ? view.live : view.freeze)}>{view.frozen ? 'Return to live view' : 'Freeze for selection'}</button>
      </details>
      {toolProps && (tab === 'Connection' ? <SettingsTool {...toolProps} /> : tab === 'Recognition' ? <TrackingTool {...toolProps} /> : <PotionsTool {...toolProps} />)}
    </>}
    {tab === 'Map' && toolProps && <>
      <MapTab snapshot={toolProps.snapshot} client={client} act={act} disabled={disabled}
        builderDisabled={builderDisabled}
        onCircuit={selectCircuit}
        onPreview={() => setAction({ name: 'nav_start', label: 'Previewed navigation route', payload: { opt_in: false } })} />
      <NavigationPanel snapshot={toolProps.snapshot} client={client} act={act} disabled={disabled}
        areas={areas} supervised={supervised}
        onInvalidate={() => { setSupervised(false); choose('dry_run', 'Decision preview'); }}
        onPreview={() => setAction({ name: 'nav_start', label: 'Previewed navigation route', payload: { opt_in: false } })}
        onSupervised={value => { setSupervised(value); setAction(previous => previous.name === 'nav_start'
          ? { ...previous, payload: { opt_in: value } } : previous); }} />
      <PositionPanel {...toolProps} image={view.frozen ? null : view.image} areas={areas} refreshAreas={refreshAreas} />
    </>}
    {tab === 'Diagnostics' && toolProps && <DiagnosticsTool {...toolProps} />}
  </>;
  if (dashboard) {
    const words: Record<string, string> = { ON: 'Bot on', OFF: 'Bot off', STARTING: 'Starting', BLOCKED: 'Blocked', DISCONNECTED: 'Disconnected' };
    const canTurnOn = !disabled && (running || starting || (fresh && selectedGate?.ready !== false));
    const reason = state.error || (running || starting ? s?.active_probe?.instruction || s?.navigation?.active && s.navigation.reason || s?.reason
      : !fresh ? 'Waiting for fresh recognition.' : selectedGate?.reason || s?.reason);
    const openPage = (name: string | null) => void act(async () => {
      if (name) setTab(name);
      if (Boolean(name) !== panel) await dashboard.settings(Boolean(name));
    });
    const potion = s?.autopotter;
    return <div className={`dashboard-overlay dash ${panel ? 'editing-layout' : ''}`}>
      <nav className="dash-side" aria-label="Dashboard pages">
        <div className="dash-brand"><NavIcon name="Overview" />Maple External</div>
        {[null, 'Bot', 'Connection', 'Recognition', 'Potions', 'Map', 'Diagnostics'].map(name =>
          <button key={name ?? 'Overview'} aria-current={(name ? panel && tab === name : !panel) ? 'page' : undefined}
            onClick={() => openPage(name)}><NavIcon name={name ?? 'Overview'} /><span>{name ?? 'Overview'}</span></button>)}
        <p className="dash-side-foot">{!s ? 'Waiting for the engine.' : s.capture_only ? 'Capture-only session. Gameplay keys are locked.' : 'Input-capable session. Existing safety checks apply.'}</p>
      </nav>
      <main className="dash-main">
        {dashboard.disconnected && <section className="dash-panel" role="alert" aria-label="Dashboard controls disconnected">
          <h2>Dashboard controls are disconnected</h2>
          <p>{dashboard.connectionIssue}</p>
          <p>Saved-path editing remains available while the engine is connected and the bot is Off.</p>
          <p>Connecting the MapleStory window supplies the picture; it does not reconnect dashboard controls.
            Close any other dashboard or native overlay that owns controls, then reload this dashboard. The bot stays Off.</p>
        </section>}
        {s && <AlarmBanner snapshot={s} onAcknowledge={id => void act(() => client.command('acknowledge', { incident_id: id }))} />}
        <div className="dash-top">
          <section className="dash-panel dash-stage dashboard-preview" aria-label="Dashboard game view">
            <GameViewport image={view.image} frozen={Boolean(view.frozen)} stale={!fresh || (layers && !previewDrawing)} selection={view.selection}
              onSelection={view.setSelection} overlay={layers && previewDrawing ? drawingLayers(previewDrawing, true) : undefined}
              onStop={() => void act(() => client.command('stop'))} />
            <div className="dash-hud" aria-label="Character status">
              <div className={`dash-who ${active ? 'on' : ''}`}><strong><span className="status-dot" />{words[status]}</strong><span>{action.label}</span></div>
              <Gauge label="HP" kind="hp" percent={potion?.readings.hp?.percent} threshold={potion?.settings.hp_threshold ?? 50} />
              <Gauge label="MP" kind="mp" percent={potion?.readings.mp?.percent} threshold={potion?.settings.mp_threshold ?? 50} />
            </div>
            <div className="dash-under">
              <div className="dash-chips" role="group" aria-label="Drawing layers">
                <label><input type="checkbox" checked={layers} onChange={e => setLayers(e.target.checked)} /> Boxes</label>
                <label><input type="checkbox" checked={attackRange} onChange={e => setAttackRange(e.target.checked)} /> Attack range</label>
                <label><input type="checkbox" checked={terrain} onChange={e => setTerrain(e.target.checked)} /> Terrain</label>
              </div>
              <span>{layers ? 'Drawings match the analyzed picture.' : 'Live game picture.'} F8 always stops gameplay.</span>
            </div>
          </section>
          <aside className="dash-panel dash-rail" aria-label="Run controls and status">
            <div className="dash-state"><strong>{words[status]}</strong>{recordingFull && <span className="overlay-recording">REC{recordLeft == null ? '' : ` ${Math.ceil(recordLeft)} s`}</span>}</div>
            <label className="dash-field">Activity
              <select value={!action.payload.circuit && ['dry_run', 'arm', 'autopotter_live'].includes(action.name) ? action.name : 'custom'} disabled={running || starting}
                onChange={e => choose(e.target.value, e.target.selectedOptions[0].text)}>
                <option value="dry_run">Decision preview</option><option value="arm" disabled={s?.capture_only}>Combat + configured potions</option>
                <option value="autopotter_live" disabled={s?.capture_only}>Potions only</option>
                {(Boolean(action.payload.circuit) || !['dry_run', 'arm', 'autopotter_live'].includes(action.name)) && <option value="custom">{action.label}</option>}
              </select></label>
            <div className="dash-row dashboard-controls">
              <button className={`dash-btn primary ${running || starting ? 'off' : ''}`} disabled={!canTurnOn} onClick={() => void toggle()}>Turn {running || starting ? 'Off' : 'On'}</button>
              <button className="dash-btn stop" onClick={() => { startRef.current = false; setStarting(false); void act(() => client.command('stop')); }}>Stop <kbd>F8</kbd></button>
            </div>
            <p className={`dash-reason ${!running && !starting && !canTurnOn ? 'block' : ''}`} aria-live="polite">{reason}</p>
            {state.notice && <p className="overlay-notice">{state.notice}</p>}
            <button className="dash-btn ghost" disabled={disabled} onClick={record}>{recordingFull ? `Stop recording${recordLeft == null ? '' : ` · ${Math.ceil(recordLeft)} s left`}` : 'Record 30 s'}</button>
            <hr />
            {s && <PlayerCapture snapshot={s} client={client} act={act} disabled={disabled} />}
            {!panel && toolProps && <WeaponRange {...toolProps} />}
            <Facts snapshot={s} />
            <hr />
            <p className="dash-keys">F6 on/off · F7 settings · F9 layers · F8 stops from anywhere.</p>
          </aside>
        </div>
        {panel ? <section className="dash-panel overlay-panel dash-settings" aria-label="Overlay settings">
          <header><h1>{tab}</h1><button className="dash-btn" onClick={() => openPage(null)}>Close <kbd>F7</kbd></button></header>
          {settingsBody}
          <footer><button className="dash-btn" onClick={() => void act(() => dashboard.quit())}>Disconnect dashboard</button></footer>
        </section> : <div className="dash-lower">
          <section className="dash-panel" aria-labelledby="dash-spot-title">
            <h2 id="dash-spot-title"><NavIcon name="Map" />Spot map</h2>
            <SpotMap map={map} snapshot={s} />
          </section>
          <section className="dash-panel" aria-labelledby="dash-journal-title">
            <h2 id="dash-journal-title"><NavIcon name="Diagnostics" />Session journal</h2>
            <Journal history={s?.history} />
          </section>
        </div>}
      </main>
    </div>;
  }
  return <div className={`native-overlay ${panel ? 'editing-layout' : ''}`}>
    {layers && drawingFresh && drawing && gameBounds?.visible && <svg className="world-layer"
      style={{ left: game.x, top: game.y, width: game.width, height: game.height }}
      viewBox={`0 0 ${drawing.frame.width} ${drawing.frame.height}`} preserveAspectRatio="none" aria-label="Live detections">
      {drawingLayers(drawing)}
    </svg>}
    <div className={`overlay-hud ${active ? 'on' : 'off'}`} role="status"
      style={layout.position('hud', { x: game.x + 14, y: game.y + 14 })}>
      <strong className="panel-drag-handle" {...layout.handlers('hud')}><span className="status-dot" /> BOT {status}{panel && <small>Drag to move</small>}</strong><span>{action.label}</span>
      <small>F6 On/Off · F7 Settings · F8 Stop · F9 Layers</small>
      {!panel && <button className="hud-settings" onClick={() => void act(() => host!.settings(true))}>⚙ Settings</button>}
      {s && <PlayerCapture snapshot={s} client={client} act={act} disabled={disabled} />}
      {state.notice && <p className="overlay-notice">{state.notice}</p>}
      <p>{state.error || (!fresh ? 'Waiting for fresh recognition' : s?.active_probe?.instruction || s?.navigation?.active && s.navigation.reason || s?.reason)}</p>
      <span>{(['hp', 'mp'] as const).map(r => `${r.toUpperCase()} ${s?.autopotter.readings[r]?.percent ?? '—'}%`).join(' · ')}</span>
      {recordingFull && <span className="overlay-recording">REC{recordLeft == null ? '' : ` ${Math.ceil(recordLeft)} s`}</span>}
    </div>
    {panel && <section className="overlay-panel" aria-label="Overlay settings"
      style={layout.position('settings', { x: game.x + game.width - 474, y: game.y + 14 })}>
      <header className="panel-drag-handle" {...layout.handlers('settings')}><h1>Maple Overlay · drag to move</h1><button onClick={() => void act(() => host!.settings(false))}>Close · F7</button></header>
      {settingsBody}
      <footer><button onClick={() => void act(() => client.command('stop'))}>Stop · F8</button>
        <button onClick={() => void act(() => host!.quit())}>Exit overlay</button></footer>
    </section>}
  </div>;
}

