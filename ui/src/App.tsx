import { useEffect, useState, useSyncExternalStore } from 'react';
import { EngineClient, resultMessage } from './client';
import { useViewport } from './useViewport';
import { GameViewport } from './GameViewport';
import { AlarmBanner } from './AlarmBanner';
import { CombatTool, DiagnosticsTool, PotionsTool, SettingsTool, TrackingTool } from './tools';
import type { Tool } from './tools';
import { useAreaEditor } from './useAreaEditor';
import { AreaCanvas, AreaEditor } from './AreaEditor';
import { PositionOverlay, PositionPanel } from './PositionPanel';
import { MapTab } from './MapTab';
import { NavigationPanel } from './NavigationPanel';
import { GoBar } from './GoBar';
import type { FarmingRoute } from './PathBuilder';

export function App({ client }: { client: EngineClient }) {
  const state = useSyncExternalStore(client.subscribe, client.getState);
  const s = state.snapshot;
  const [tool, setTool] = useState<Tool | null>(null);
  const [runMode, setRunMode] = useState<'preview' | 'live' | 'navigation' | 'farming'>('preview');
  const [navigationTab, setNavigationTab] = useState<'map' | 'routes' | 'setup'>('map');
  const [farmMinutes, setFarmMinutes] = useState(15);
  const [circuit, setCircuit] = useState<FarmingRoute | null>(null);
  useEffect(() => {
    if (circuit && s?.position?.area_id && circuit.area_id !== s.position.area_id) setCircuit(null);
  }, [circuit, s?.position?.area_id]);
  const [feedSeconds, setFeedSeconds] = useState('');
  const [farmHp, setFarmHp] = useState(50);
  const [farmMp, setFarmMp] = useState(50);
  const [learnMoves, setLearnMoves] = useState(false);
  const [supervised, setSupervised] = useState(false);
  const [routeCurrent, setRouteCurrent] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [readySince, setReadySince] = useState<number | null>(null);
  const view = useViewport(client, s, state.connected);
  const area = useAreaEditor(client, s?.session_id, s?.area_editing, s?.command_epoch);
  const areaEditing = area.editing || Boolean(s?.area_editing);
  useEffect(() => client.start(), [client]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 100); return () => clearInterval(timer); }, []);
  useEffect(() => { setRunMode('preview'); setSupervised(false); setRouteCurrent(false); }, [s?.session_id]);
  const disabled = state.busy || !state.connected || state.needsReload || state.process !== 'running';
  const gate = runMode === 'navigation' ? {
    ready: Boolean(!s?.capture_only && s?.navigation?.ready && routeCurrent && supervised),
    reason: s?.navigation?.blocker ?? (!routeCurrent ? 'Preview the selected route first' : !supervised ? 'Confirm that you will supervise this route' : 'Navigation ready'),
  } : s?.readiness[runMode === 'preview' ? 'preview' : 'combat'];
  const fresh = Boolean(s?.frame.available && s.frame.captured_at != null && now - s.frame.captured_at * 1000 <= 1500);
  const displayFrame = s?.preview_frame ?? s?.frame;
  const displayed = Boolean(view.image && !view.frozen && (s?.preview_frame
    ? view.image.sourceId === displayFrame?.source_id : view.image.key === displayFrame?.id));
  const liveFrame = state.connected && displayed && Boolean(displayFrame?.available
    && view.image?.capturedAt != null && now - view.image.capturedAt * 1000 <= 1000);
  const eligible = !disabled && !areaEditing && (runMode !== 'farming' || (Number(feedSeconds) >= 1 && Number(feedSeconds) <= 3600 && farmMinutes >= 1 && farmMinutes <= 120 && farmHp >= 1 && farmHp <= 95 && farmMp >= 1 && farmMp <= 95)) && Boolean(gate?.ready) && fresh && (s?.preview_frame ? liveFrame : displayed);
  useEffect(() => { setReadySince(eligible ? Date.now() : null); }, [eligible]);
  const canStart = eligible && readySince !== null && now - readySince >= 1000;
  const act = async (operation: () => Promise<unknown>) => {
    try {
      const result = await operation();
      if (result !== undefined) client.message(resultMessage(result));
    } catch (error) { client.fail(error); }
  };
  const showTool = (value: Tool) => setTool(previous => previous === value ? null : value);
  const start = () => act(async () => {
    if (runMode === 'navigation') {
      const result = await client.command('nav_start', { opt_in: supervised });
      setSupervised(false); // A started route consumes the opt-in; a refused start keeps it.
      return result;
    }
    return client.command(runMode === 'preview' ? 'dry_run' : 'arm', runMode === 'farming' ? {
      farming: { session_minutes: farmMinutes, feed_seconds: Number(feedSeconds), hp_threshold: farmHp, mp_threshold: farmMp, learn_moves: learnMoves },
      ...(circuit ? { circuit: { id: circuit.id, revision: circuit.revision } } : {}),
    } : {});
  });
  const stop = (name: 'stop' | 'pause') => act(async () => {
    await client.command(name);
    client.message(name === 'pause' ? 'Paused. All gameplay input released. Press Start to run again.' : 'Stopped. All gameplay input released.');
  });
  const props = s ? {
    snapshot: s, client, act, disabled: disabled || areaEditing, selected: view.selected, clear: view.clear,
    runMode, setRunMode,
  } : null;
  const alarmId = s?.alarm.incident_id ?? s?.stop?.id;
  const toolName = tool === 'Tracking' ? 'Recognition' : tool;

  return <div className="app-shell">
    <header className="app-header">
      <div className="brand"><span className="brand-mark" aria-hidden="true">M</span><div><h1>Maple External</h1><span className="brand-subtitle">Hunting workspace</span></div></div>
      <span className={`session-badge ${state.connected ? '' : 'offline'}`}>{state.process !== 'running' ? state.process : !state.connected ? 'Engine disconnected' : s?.capture_only ? 'Capture only · input locked' : 'Input-capable session'}</span>
      {s?.alarm.active && <button className="danger" disabled={!alarmId} onClick={() => alarmId && void act(() => client.command('acknowledge', { incident_id: alarmId }))}>Acknowledge alarm</button>}
      <div className="run-controls" aria-label="Run controls">
        <select aria-label="Run mode" value={runMode} disabled={disabled || areaEditing} onChange={e => {
          setRunMode(e.target.value as 'preview' | 'live' | 'navigation' | 'farming');
          if (e.target.value === 'navigation') { setTool('Navigation'); setNavigationTab('routes'); }
        }}>
          <option value="preview">Preview</option><option value="navigation">Navigation</option><option value="live" disabled={!s || s.capture_only}>Live combat</option><option value="farming" disabled={!s || s.capture_only}>Farming (pet potions)</option>
        </select>
        <button className="primary" disabled={!canStart} title={gate?.reason ?? 'Waiting for the engine'} onClick={() => void start()}><span aria-hidden="true">▶</span> {runMode === 'preview' ? 'Start preview' : runMode === 'navigation' ? 'Start navigation' : runMode === 'farming' ? 'Start farming' : 'Start combat'}</button>
        <button disabled={state.process !== 'running'} onClick={() => void stop('pause')}>Pause</button>
        <button className="stop-button" disabled={state.process !== 'running'} onClick={() => void stop('stop')}>Stop <kbd>F8</kbd></button>
      </div>
      {!canStart && state.connected && <p className="run-blocker">{gate?.ready ? 'Waiting for steady fresh recognition' : gate?.reason}</p>}
    </header>
    {runMode === 'farming' && <section className="go-bar" aria-label="Farming settings">
      <span>{circuit ? `${circuit.name} · revision ${circuit.revision} · ${circuit.stops.length} stops${circuit.loop ? ' · loop' : ''}` : 'Automatic platform rotation'}</span>
      {circuit && <button onClick={() => setCircuit(null)}>Use automatic rotation</button>}
      <label>Session minutes <input type="number" min="1" max="120" value={farmMinutes} onChange={e => setFarmMinutes(Number(e.target.value))} /></label>
      <label>Feed every (seconds) <input type="number" min="1" max="3600" value={feedSeconds} placeholder="Required" onChange={e => setFeedSeconds(e.target.value)} /></label>
      <label>Pet HP trigger % <input type="number" min="1" max="95" value={farmHp} onChange={e => setFarmHp(Number(e.target.value))} /></label>
      <label>Pet MP trigger % <input type="number" min="1" max="95" value={farmMp} onChange={e => setFarmMp(Number(e.target.value))} /></label>
      <label title="When a platform is clear, try one unproven move to a neighbouring platform. A success is saved as a proof; any failed move stops the batch."><input type="checkbox" checked={learnMoves} onChange={e => setLearnMoves(e.target.checked)} /> Learn new platform moves (I'm supervising)</label>
      <span>Pet supplies both potions. Stops after 5 seconds below a trigger. Feeding timing needs verification; Home sends food without confirming consumption.</span>
    </section>}
    <nav className="workspace-nav" aria-label="Workspace tools">
      <button aria-pressed={!tool} onClick={() => setTool(null)}>Overview</button>
      {(['Tracking', 'Combat', 'Navigation', 'Potions'] as const).map(name => <button key={name} aria-pressed={tool === name} onClick={() => showTool(name)}>{name === 'Tracking' ? 'Recognition' : name}</button>)}
      <div className="nav-spacer" /><button aria-pressed={tool === 'Settings'} onClick={() => showTool('Settings')}>Settings</button>
      <button className="quiet" aria-pressed={tool === 'Diagnostics'} onClick={() => showTool('Diagnostics')}>Diagnostics</button>
    </nav>
    {state.needsReload && <section className="alarm-banner" aria-label="Reconnect workspace">
      <div><span className="eyebrow">Engine restarted</span><p>Reload this workspace to reconnect. Gameplay input stays stopped.</p></div>
      <button onClick={() => location.reload()}>Reload workspace</button>
    </section>}
    {s && <AlarmBanner snapshot={s} onAcknowledge={id => void act(() => client.command('acknowledge', { incident_id: id }))} />}
    {s && !s.capture_only && <GoBar snapshot={s} client={client} act={act} disabled={disabled || areaEditing} />}
    {state.error && <section className="blocked-banner" role="alert" aria-label="Action blocked">
      <div><span className="eyebrow">Action blocked · no keys sent</span><p>{state.error}</p></div>
      <button onClick={() => client.message('')}>Dismiss</button>
    </section>}
    <main className={`workspace ${tool ? 'with-dock' : ''} ${tool === 'Navigation' ? 'navigation-workspace' : ''}`}>
      <section className="preview-panel" aria-label="Live game workspace">
        <div className="preview-heading"><div><span className="eyebrow">{area.editing ? 'Area reference' : view.frozen ? 'Frozen frame' : 'Game view'}</span>
          <span className="map-name">{area.editing ? area.draft?.name ?? 'Area drawing' : s?.catalog?.active_map || s?.window?.title || 'Waiting for connection'}</span></div>
          <span className={`view-badge ${!liveFrame || area.editing ? 'stale' : ''}`}>{area.editing ? 'Editing · input stopped' : view.frozen ? 'Selection mode' : liveFrame ? 'Live picture' : !state.connected ? 'Disconnected · last frame' : view.image ? 'Last frame · waiting for capture' : 'Waiting for fresh frame'}</span></div>
        {area.editing ? <AreaCanvas workspace={area} disabled={disabled || area.working} /> : <GameViewport image={view.image} frozen={Boolean(view.frozen)} stale={!liveFrame} selection={view.selection} onSelection={view.setSelection}
          overlay={!liveFrame ? null : <PositionOverlay position={s?.position} showText={tool !== 'Navigation'} />}
          onStop={() => void stop('stop')} stopDisabled={state.process !== 'running'} />}
        {area.editing ? <div className="preview-toolbar"><span className="area-reference-note">{area.view?.name ?? 'Capture a reference from Navigation'} · fixed image</span>
          <div className="nav-spacer" /><button disabled={disabled || area.working} onClick={() => void area.end()}>Exit area editing</button></div> : <>
        <div className="preview-toolbar" aria-label="Capture tools">
          <button disabled={disabled || view.freezing || !s?.frame.available} onClick={() => void act(view.freeze)}>{view.freezing ? 'Freezing…' : 'Freeze & select'}</button>
          {(view.frozen || view.freezing || s?.calibrating) && <button disabled={!state.connected || state.process !== 'running'} onClick={() => void act(view.live)}>Return to live view</button>}
          <div className="nav-spacer" /><button disabled={disabled || !s?.frame.available} onClick={() => void act(() => client.command('save'))}>Screenshot</button>
          <button disabled={disabled} onClick={() => void act(() => client.command('clip'))}>Save last clip</button>
        </div>
        {view.frozen && <p className="selection-hint">{view.selection ? `${view.selection.x}, ${view.selection.y} · ${view.selection.width} × ${view.selection.height} native pixels` : 'Drag over the preview to select native game pixels.'}</p>}
        </>}
        <footer className="preview-status"><div><span className="status-label">Player</span><strong>{s?.health && !s.health.recognition ? 'Waiting for recognition' : !s?.player ? 'Not recognized' : s.player.tracked ? 'Tracked · awaiting confirmation' : 'Confirmed'}</strong></div>
          <div><span className="status-label">Action</span><strong>{state.process !== 'running' ? state.process : s?.mode?.replaceAll('_', ' ') ?? 'Stopped'}</strong></div>
          <p>{s?.mode === 'capture' ? s.health?.reason ?? 'Viewing only · no game keys sent' : s?.reason || 'Connect the game from Settings. Keyboard output stays off until explicitly enabled.'}</p>
          {s?.health?.warning && <p className="warning-copy" role="alert">{s.health.warning}</p>}
        </footer>
      </section>
      <aside hidden={!tool} className="tool-dock" aria-label={tool ? `${toolName} tool` : 'Workspace tool'}>
        <header className="dock-heading"><div><span className="eyebrow">Workspace tool</span><h2>{toolName}</h2></div><button aria-label="Close tool panel" title="Return to full-width overview" onClick={() => setTool(null)}>×</button></header>
        <div className="dock-body"><div hidden={tool !== 'Navigation'}>
          <nav className="navigation-tabs" aria-label="Navigation pages">
            <button aria-pressed={navigationTab === 'map'} onClick={() => setNavigationTab('map')}>Map</button>
            <button aria-pressed={navigationTab === 'routes'} onClick={() => setNavigationTab('routes')}>Routes</button>
            <button aria-pressed={navigationTab === 'setup'} onClick={() => setNavigationTab('setup')}>Setup</button>
          </nav>
          <div hidden={navigationTab !== 'map'}>{props && <MapTab snapshot={props.snapshot} client={client} act={act} disabled={props.disabled} onCircuit={setCircuit}
            onPreview={() => { setRouteCurrent(true); setSupervised(false); setRunMode('navigation'); setNavigationTab('routes'); }} />}</div>
          <div hidden={navigationTab !== 'routes'}>{props && <NavigationPanel key={s?.position?.area_id ?? 'no-map'} snapshot={props.snapshot} client={client} act={act} disabled={props.disabled}
            onInvalidate={() => { setRouteCurrent(false); setSupervised(false); }} onPreview={() => { setRouteCurrent(true); setRunMode('navigation'); }} supervised={supervised} onSupervised={setSupervised} areas={area.areas} />}</div>
          <div hidden={navigationTab !== 'setup'}>{props && <PositionPanel key={s?.position?.area_id ?? 'no-map'} snapshot={props.snapshot} image={view.frozen ? null : view.image} client={client} act={act} disabled={props.disabled} areas={area.areas} refreshAreas={area.refresh} />}
            <details className="advanced-editor"><summary>Advanced: draw by hand</summary><AreaEditor workspace={area} active={tool === 'Navigation' && navigationTab === 'setup'} connected={state.connected} disabled={disabled} /></details></div></div>
          {tool !== 'Navigation' && (!props ? <p>Waiting for the engine connection…</p> : tool === 'Tracking' ? <TrackingTool {...props} /> : tool === 'Combat' ? <CombatTool {...props} /> : tool === 'Potions' ? <PotionsTool key={s!.session_id} {...props} /> : tool === 'Settings' ? <SettingsTool key={s!.session_id} {...props} /> : tool === 'Diagnostics' ? <DiagnosticsTool {...props} /> : null)}</div>
      </aside>
    </main>
    <div className="feedback" role="status" aria-live="polite">{state.notice || (state.connected ? 'Ready when you are. Preview sends no keyboard input.' : 'Connecting to the local engine…')}
      </div>
    <footer className="app-footer"><span>Screenshot in · bounded keyboard out</span><span>{s?.capture_only ? 'Capture-only session' : 'Supervised session'} · No automatic resume</span></footer>
  </div>;
}
