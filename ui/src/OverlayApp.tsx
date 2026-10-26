import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { OverlayClient, freshDetections, isRunning } from './overlay';
import type { OverlayAction } from './overlay';
import type { AreaProfile, Detection, Rect } from './contracts';
import { useOverlayLayout } from './overlayLayout';
import { useViewport } from './useViewport';
import { GameViewport } from './GameViewport';
import { SettingsTool, TrackingTool, PotionsTool, DiagnosticsTool } from './tools';
import { PositionPanel, MapSketch } from './PositionPanel';
import { GoBar } from './GoBar';
import { NavigationPanel } from './NavigationPanel';
import { AlarmBanner } from './AlarmBanner';
import { SavedTerrainOverlay } from './SavedTerrainOverlay';
import './overlay.css';

export function OverlayApp({ client }: { client: OverlayClient }) {
  const state = useSyncExternalStore(client.subscribe, client.getState);
  const s = state.snapshot;
  const [panel, setPanel] = useState(true);
  const [gameBounds, setGameBounds] = useState<(Rect & { visible: boolean }) | null>(null);
  const layout = useOverlayLayout(panel);
  const [tab, setTab] = useState('Bot');
  const [layers, setLayers] = useState(true);
  const [terrain, setTerrain] = useState(true);
  const [action, setAction] = useState<OverlayAction>({ name: 'dry_run', payload: {}, label: 'Decision preview' });
  const [now, setNow] = useState(Date.now());
  const [map, setMap] = useState<AreaProfile | null>(null);
  const [areas, setAreas] = useState<{ id: string; name: string; revision: number }[]>([]);
  const [starting, setStarting] = useState(false);
  const [supervised, setSupervised] = useState(false);
  const startRef = useRef(false);
  const wasRunning = useRef(false);
  const dataKey = useRef('');
  const currentToggle = useRef<() => void>(() => {});
  const view = useViewport(client, s, state.connected && panel);
  const running = isRunning(s);
  // Status can arrive between timer ticks; don't compare a new frame against
  // the previous tick and incorrectly classify it as coming from the future.
  const fresh = freshDetections(s, state.connected, Math.max(now, Date.now()));
  const disabled = !state.connected || state.busy || state.needsReload;
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
  useEffect(() => { client.select = setAction; return () => { client.select = () => {}; }; }, [client]);
  useEffect(() => {
    const timer = setInterval(() => { setNow(Date.now()); window.mapleOverlay?.heartbeat(); }, 200);
    const unsub = window.mapleOverlay?.subscribe(event => {
      if (event.type === 'panel') setPanel(Boolean(event.value));
      if (event.type === 'game-bounds') setGameBounds(event.value as (Rect & { visible: boolean }) | null);
      if (event.type === 'toggle') currentToggle.current();
      if (event.type === 'off') { startRef.current = false; setStarting(false); void act(() => client.command('stop')); }
      if (event.type === 'layers') setLayers(value => !value);
      if (event.type === 'error') client.fail(event.value);
    });
    return () => { clearInterval(timer); unsub?.(); };
  }, [client]);
  useEffect(() => {
    setAction({ name: 'dry_run', payload: {}, label: 'Decision preview' });
    setMap(null);
  }, [s?.session_id]);
  useEffect(() => {
    if (!s || !state.connected || state.busy) return;
    const key = `${s.session_id}:${s.position?.area_id}:${s.position?.teaching?.map_revision}`;
    if (key === dataKey.current) return;
    dataKey.current = key;
    setMap(null);
    void act(async () => {
      await refreshAreas();
      if (s.position?.area_id) {
        const value = await client.command<{ profile: AreaProfile }>('area_load', { area_id: s.position.area_id });
        if (dataKey.current === key) setMap(value.profile);
      }
    });
  }, [client, s?.session_id, s?.position?.area_id, s?.position?.teaching?.map_revision, state.connected, state.busy]);
  const toggle = async () => {
    if (running || startRef.current) {
      startRef.current = false; setStarting(false);
      await act(() => client.command('stop'));
      client.message('F6 · bot switched Off'); return;
    }
    if (!panel && !s?.focused) { client.message('F6 · focus the game to turn On; F8 always stops'); return; }
    if (disabled || !fresh) { client.message('OFF · waiting for fresh recognition and an engine connection'); return; }
    client.message(`F6 · starting ${action.label}${action.name === 'dry_run' ? ' (no gameplay keys)' : ''}`);
    startRef.current = true; setStarting(true);
    try {
      if (panel) await window.mapleOverlay?.settings(false);
      if (!startRef.current) return;
      await client.execute(action);
      const result = await client.readStatus();
      if (!isRunning(result)) client.message(`${action.label} stopped: ${result.reason}`);
    } catch (e) { client.fail(e); }
    finally { startRef.current = false; setStarting(false); }
  };
  currentToggle.current = () => void toggle();
  const choose = (name: string, label: string) => setAction({ name, label, payload: {} });
  const position = s?.position;
  const active = state.connected && fresh && running;
  const status = !state.connected ? 'DISCONNECTED' : s?.alarm.active ? 'BLOCKED' : starting ? 'STARTING'
    : active ? (s?.mode.includes('wait') || s?.mode === 'pending_arm' ? 'STARTING' : 'ON') : 'OFF';
  const detection = (item: Detection, key: string, color: string) => <g key={key} stroke={color}>
    <rect {...item.box} fill="none" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    <text x={item.box.x} y={Math.max(14, item.box.y - 5)} fill={color} stroke="#091019" strokeWidth="3" paintOrder="stroke"
      fontSize="13">{key} · {item.tracked ? 'tracked' : `${Math.round(item.confidence * 100)}% similarity`}</text>
  </g>;
  const toolProps = s ? { snapshot: s, client, act, disabled, selected: view.selected, clear: view.clear, selectOnly: true,
    runMode: (action.name === 'arm' ? 'live' : 'preview') as 'live' | 'preview',
    setRunMode: (mode: 'live' | 'preview' | 'navigation') => choose(mode === 'live' ? 'arm' : 'dry_run', mode),
  } : null;
  const game = gameBounds ?? { x: 0, y: 0, width: innerWidth, height: innerHeight };
  return <div className={`native-overlay ${panel ? 'editing-layout' : ''}`}>
    {layers && fresh && s && gameBounds?.visible && <svg className="world-layer"
      style={{ left: game.x, top: game.y, width: game.width, height: game.height }}
      viewBox={`0 0 ${s.frame.width} ${s.frame.height}`} preserveAspectRatio="none" aria-label="Live detections">
      {terrain && <SavedTerrainOverlay map={map} position={position} now={Math.max(now, Date.now())} />}
      {s.player && detection(s.player, 'Player', '#81edbb')}
      {s.monsters?.map((item, i) => detection(item, `${item.kind} ${i + 1}`, '#ffbd72'))}
      {s.target && detection(s.target, 'Target', '#ff6b89')}
    </svg>}
    <div className={`overlay-hud ${active ? 'on' : 'off'}`} role="status"
      style={layout.position('hud', { x: game.x + 14, y: game.y + 14 })}>
      <strong className="panel-drag-handle" {...layout.handlers('hud')}><span className="status-dot" /> BOT {status}{panel && <small>Drag to move</small>}</strong><span>{action.label}</span>
      <small>F6 On/Off · F7 Settings · F8 Stop · F9 Layers</small>
      {state.notice && <p className="overlay-notice">{state.notice}</p>}
      <p>{state.error || (!fresh ? 'Waiting for fresh recognition' : s?.active_probe?.instruction || s?.navigation?.active && s.navigation.reason || s?.reason)}</p>
      <span>{(['hp', 'mp'] as const).map(r => `${r.toUpperCase()} ${s?.autopotter.readings[r]?.percent ?? '—'}%`).join(' · ')}</span>
    </div>
    {layers && terrain && map?.boundary && <section className="terrain-inset"
      style={layout.position('terrain', { x: game.x + 14, y: game.y + game.height - 240 })}>
      <strong className="panel-drag-handle" {...layout.handlers('terrain')}>Saved terrain · {map.name}</strong>
      <MapSketch geometry={map} feet={fresh && position && !position.stale ? position.feet : null} />
      <small>{position?.stale ? 'Position stale' : position?.reason} · saved geometry, not live terrain detection</small>
    </section>}
    {panel && <section className="overlay-panel" aria-label="Overlay settings"
      style={layout.position('settings', { x: game.x + game.width - 474, y: game.y + 14 })}>
      <header className="panel-drag-handle" {...layout.handlers('settings')}><h1>Maple Overlay · drag to move</h1><button onClick={() => void window.mapleOverlay?.settings(false)}>Close · F7</button></header>
      <p>Bot is Off while settings are open. Closing settings never resumes it.</p>
      <p>Drag panel headings anywhere on the desktop, including outside the game. <button onClick={layout.reset}>Reset positions</button></p>
      <nav>{['Bot', 'Connection', 'Recognition', 'Potions', 'Map', 'Diagnostics'].map(name =>
        <button key={name} aria-pressed={tab === name} onClick={() => setTab(name)}>{name}</button>)}</nav>
      {state.error && <p role="alert" className="warning-copy">{state.error}</p>}
      {state.notice && <p role="status">{state.notice}</p>}
      {s && <AlarmBanner snapshot={s} onAcknowledge={id => void act(() => client.command('acknowledge', { incident_id: id }))} />}
      {tab === 'Bot' && <>
        <label>Activity<select value={['dry_run', 'arm', 'autopotter_live'].includes(action.name) ? action.name : 'custom'} onChange={e => choose(e.target.value, e.target.selectedOptions[0].text)}>
          <option value="dry_run">Decision preview</option><option value="arm" disabled={s?.capture_only}>Combat + configured potions</option>
          <option value="autopotter_live" disabled={s?.capture_only}>Potions only</option>
          {!['dry_run', 'arm', 'autopotter_live'].includes(action.name) && <option value="custom">{action.label}</option>}
        </select></label>
        <button className="primary master-toggle" disabled={disabled} onClick={() => void toggle()}>Turn {running || starting ? 'Off' : 'On'} · F6</button>
        <p>On closes settings and starts the existing countdown. Focus the game. F8 always stops. Combat and navigation retain configured potion priority.</p>
        {s && <GoBar snapshot={s} client={client} act={act} disabled={disabled} availableAreas={areas} selectOnly />}
        <label><input type="checkbox" checked={layers} onChange={e => setLayers(e.target.checked)} /> Show detection layers</label>
        <label><input type="checkbox" checked={terrain} onChange={e => setTerrain(e.target.checked)} /> Show saved terrain and position</label>
        <p>{s?.capture_only ? 'Capture-only session · gameplay input locked' : 'Input-capable session · existing verification gates apply'}</p>
      </>}
      {['Connection', 'Recognition', 'Potions'].includes(tab) && <>
        <details><summary>Calibration picture and selection</summary>
          <GameViewport image={view.image} frozen={Boolean(view.frozen)} selection={view.selection} onSelection={view.setSelection} />
          <button disabled={disabled} onClick={() => void act(view.frozen ? view.live : view.freeze)}>{view.frozen ? 'Return to live view' : 'Freeze for selection'}</button>
        </details>
        {toolProps && (tab === 'Connection' ? <SettingsTool {...toolProps} /> : tab === 'Recognition' ? <TrackingTool {...toolProps} /> : <PotionsTool {...toolProps} />)}
      </>}
      {tab === 'Map' && toolProps && <>
        <NavigationPanel snapshot={toolProps.snapshot} client={client} act={act} disabled={disabled}
          areas={areas} supervised={supervised}
          onInvalidate={() => { setSupervised(false); choose('dry_run', 'Decision preview'); }}
          onPreview={() => setAction({ name: 'nav_start', label: 'Previewed navigation route', payload: { opt_in: false } })}
          onSupervised={value => { setSupervised(value); setAction(previous => previous.name === 'nav_start'
            ? { ...previous, payload: { opt_in: value } } : previous); }} />
        <PositionPanel {...toolProps} areas={areas} refreshAreas={refreshAreas} />
      </>}
      {tab === 'Diagnostics' && toolProps && <DiagnosticsTool {...toolProps} />}
      <footer><button onClick={() => void act(() => client.command('stop'))}>Stop · F8</button>
        <button onClick={() => void window.mapleOverlay?.quit()}>Exit overlay</button></footer>
    </section>}
  </div>;
}
