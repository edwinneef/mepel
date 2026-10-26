import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { EngineClient, resultMessage } from './client';
import { useViewport } from './useViewport';
import { GameViewport } from './GameViewport';
import { AlarmBanner } from './AlarmBanner';
import { CombatTool, DiagnosticsTool, PotionsTool, SettingsTool, TrackingTool } from './tools';
import type { Tool } from './tools';
import { useAreaEditor } from './useAreaEditor';
import { AreaCanvas, AreaEditor } from './AreaEditor';
import { PositionOverlay, PositionPanel } from './PositionPanel';

export function App({ client }: { client: EngineClient }) {
  const state = useSyncExternalStore(client.subscribe, client.getState);
  const s = state.snapshot;
  const [tool, setTool] = useState<Tool | null>(null);
  const [runMode, setRunMode] = useState<'preview' | 'live'>('preview');
  const [now, setNow] = useState(Date.now());
  const [readySince, setReadySince] = useState<number | null>(null);
  const openedSession = useRef<string | null>(null);
  useEffect(() => {
    if (s && openedSession.current !== s.session_id) {
      openedSession.current = s.session_id;
      if (s.position?.teaching?.phase) setTool('Navigation');
    }
  }, [s]);
  const view = useViewport(client, s, state.connected);
  const area = useAreaEditor(client, s?.session_id, s?.area_editing, s?.command_epoch);
  const areaEditing = area.editing || Boolean(s?.area_editing);
  useEffect(() => client.start(), [client]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 100); return () => clearInterval(timer); }, []);
  useEffect(() => { setRunMode('preview'); }, [s?.session_id]);
  const disabled = state.busy || !state.connected || state.needsReload || state.process !== 'running';
  const gate = s?.readiness[runMode === 'preview' ? 'preview' : 'combat'];
  const fresh = Boolean(s?.frame.available && s.frame.captured_at != null && now - s.frame.captured_at * 1000 <= 500);
  const displayFrame = s?.preview_frame ?? s?.frame;
  const displayed = Boolean(view.image && !view.frozen && (s?.preview_frame
    ? view.image.sourceId === displayFrame?.source_id : view.image.key === displayFrame?.id));
  const liveFrame = state.connected && displayed && Boolean(displayFrame?.available
    && view.image?.capturedAt != null && now - view.image.capturedAt * 1000 <= 1000);
  const eligible = !disabled && !areaEditing && Boolean(gate?.ready) && fresh && (s?.preview_frame ? liveFrame : displayed);
  useEffect(() => { setReadySince(eligible ? Date.now() : null); }, [eligible]);
  const canStart = eligible && readySince !== null && now - readySince >= 1000;
  const act = async (operation: () => Promise<unknown>) => {
    try {
      const result = await operation();
      if (result !== undefined) client.message(resultMessage(result));
    } catch (error) { client.fail(error); }
  };
  const showTool = (value: Tool) => setTool(previous => previous === value ? null : value);
  const start = () => act(() => client.command(runMode === 'preview' ? 'dry_run' : 'arm'));
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
        <select aria-label="Run mode" value={runMode} disabled={disabled || areaEditing} onChange={e => setRunMode(e.target.value as 'preview' | 'live')}>
          <option value="preview">Preview</option><option value="live" disabled={!s || s.capture_only}>Live combat</option>
        </select>
        <button className="primary" disabled={!canStart} title={gate?.reason ?? 'Waiting for the engine'} onClick={() => void start()}><span aria-hidden="true">▶</span> {runMode === 'preview' ? 'Start preview' : 'Start combat'}</button>
        <button disabled={state.process !== 'running'} onClick={() => void stop('pause')}>Pause</button>
        <button className="stop-button" disabled={state.process !== 'running'} onClick={() => void stop('stop')}>Stop <kbd>F8</kbd></button>
      </div>
      {!canStart && state.connected && <p className="run-blocker">{gate?.ready ? 'Waiting for steady fresh recognition' : gate?.reason}</p>}
    </header>
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
    <main className={`workspace ${tool ? 'with-dock' : ''} ${tool === 'Navigation' ? 'navigation-workspace' : ''}`}>
      <section className="preview-panel" aria-label="Live game workspace">
        <div className="preview-heading"><div><span className="eyebrow">{area.editing ? 'Area reference' : view.frozen ? 'Frozen frame' : 'Game view'}</span>
          <span className="map-name">{area.editing ? area.draft?.name ?? 'Area teaching' : s?.catalog?.active_map || s?.window?.title || 'Waiting for connection'}</span></div>
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
        </footer>
      </section>
      <aside hidden={!tool} className="tool-dock" aria-label={tool ? `${toolName} tool` : 'Workspace tool'}>
        <header className="dock-heading"><div><span className="eyebrow">Workspace tool</span><h2>{toolName}</h2></div><button aria-label="Close tool panel" title="Return to full-width overview" onClick={() => setTool(null)}>×</button></header>
        <div className="dock-body"><div hidden={tool !== 'Navigation'}>{props && <PositionPanel key={s?.position?.area_id ?? 'no-map'} snapshot={props.snapshot} client={client} act={act} disabled={props.disabled} areas={area.areas} refreshAreas={area.refresh} />}
            <details className="advanced-editor"><summary>Advanced: draw by hand</summary><AreaEditor workspace={area} active={tool === 'Navigation'} connected={state.connected} disabled={disabled} /></details></div>
          {tool !== 'Navigation' && (!props ? <p>Waiting for the engine connection…</p> : tool === 'Tracking' ? <TrackingTool {...props} /> : tool === 'Combat' ? <CombatTool {...props} /> : tool === 'Potions' ? <PotionsTool key={s!.session_id} {...props} /> : tool === 'Settings' ? <SettingsTool key={s!.session_id} {...props} /> : tool === 'Diagnostics' ? <DiagnosticsTool {...props} /> : null)}</div>
      </aside>
    </main>
    <div className={`feedback ${state.error ? 'error' : ''}`} role="status" aria-live="polite">{state.error || state.notice || (state.connected ? 'Ready when you are. Preview sends no keyboard input.' : 'Connecting to the local engine…')}
      </div>
    <footer className="app-footer"><span>Screenshot in · bounded keyboard out</span><span>{s?.capture_only ? 'Capture-only session' : 'Supervised session'} · No automatic resume</span></footer>
  </div>;
}
