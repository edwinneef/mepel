import { PlayerCapture, tagGroups } from './PlayerCapture';
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import type { Selection, Snapshot, WindowInfo } from './contracts';
import type { EngineClient } from './client';

export type Tool = 'Tracking' | 'Combat' | 'Navigation' | 'Potions' | 'Settings' | 'Diagnostics';
type Act = (operation: () => Promise<unknown>) => Promise<void>;
export interface ToolProps {
  snapshot: Snapshot; client: EngineClient; act: Act; disabled: boolean;
  selected: () => Selection; clear: () => void;
  runMode: 'preview' | 'live' | 'navigation' | 'farming'; setRunMode: (mode: 'preview' | 'live' | 'navigation') => void;
  selectOnly?: boolean;
  startInstruction?: string;
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return <section className="tool-group"><h3>{title}</h3>{children}</section>;
}

function Data({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

export function TrackingTool({ snapshot: s, client, act, selected, disabled }: ToolProps) {
  const [poseIdentity, setPoseIdentity] = useState('');
  const [poseOutfit, setPoseOutfit] = useState('default');
  const poses = s.pose_collection;
  const teach = (kind: string) => act(() => client.command('template', { ...selected(), kind }));
  return <><p className="tool-intro">Freeze the preview, then draw a tight rectangle around the example.</p>
    <PlayerCapture snapshot={s} client={client} act={act} disabled={disabled} />
    <Group title="Player identity"><p>Include the player's feet. A name tag helps recognition through gear changes and climbing.</p>
      <div className="button-grid"><button disabled={disabled} onClick={() => void teach('player')}>Add player</button>
        <button disabled={disabled} onClick={() => void teach('nametag')}>Add name tag</button></div>
      <p className="reading">{s.player ? `${s.player.tracked ? 'Tracked' : 'Confirmed'} · ${(s.player.confidence * 100).toFixed(0)}% similarity` : 'Player not recognized'}</p>
    </Group>
    <Group title="Pose collection">
      <p>Save candidate appearances while you play. This sends no input and does not change recognition.</p>
      <label>Character name<select aria-label="Pose character" disabled={disabled || poses?.enabled} value={poseIdentity} onChange={event => setPoseIdentity(event.target.value)}>
        <option value="">Select a taught name</option>{poses && tagGroups(poses.identities, poses.labels).map(item => <option key={item.ids[0]} value={item.ids[0]}>{item.name}</option>)}
      </select></label>
      <label>Outfit label<input aria-label="Pose outfit" disabled={disabled || poses?.enabled} value={poseOutfit} onChange={event => setPoseOutfit(event.target.value)} /></label>
      <p>Use a new outfit label to start a separate collection.</p>
      {poses?.identity && <p>Collection: {poses.identity.slice(0, 6)} / {poses.outfit}</p>}
      <button disabled={disabled || !poses || (!poses.enabled && (!poseIdentity || !/^[a-zA-Z0-9_-]{1,64}$/.test(poseOutfit)))} onClick={() => void act(() => client.command('pose_collection', poses?.enabled ? { enabled: false } : { enabled: true, identity: poseIdentity, outfit: poseOutfit }))}>{poses?.enabled ? 'Stop pose collection' : 'Start pose collection'}</button>
      <p className="reading">{poses ? `${poses.reason} / ${poses.saved}/${poses.limit} saved / ${poses.duplicates} duplicates / ${poses.rejected} rejected / ${poses.pending} pending` : 'Pose collection unavailable'}</p>
    </Group>
    <Group title="Enemy library"><p>{s.catalog?.species ?? 0} species · {s.catalog?.frames ?? 0} cached frames</p>
      <p>Catalog enemies are automatic. Add examples only for missing types.</p>
      <div className="button-grid"><button disabled={disabled} onClick={() => void teach('monster')}>Add monster</button>
        <button disabled={disabled} onClick={() => void act(() => client.command('reload_templates'))}>Reload templates</button></div>
      <details><summary>Loaded species</summary><p>{s.catalog?.names?.join(', ') || 'No catalog installed.'}</p></details>
    </Group>
    <Group title="Current detection"><Data value={{ player: s.player, monsters: s.monsters?.length, target: s.target }} /></Group>
  </>;
}

export function CombatTool({ snapshot: s, runMode, setRunMode }: ToolProps) {
  return <><p className="tool-intro">Preview decisions first. Use Start in the header when ready.</p>
    <Group title="Run mode"><label>Output<select value={runMode} onChange={e => setRunMode(e.target.value as 'preview' | 'live')}>
      {runMode === 'farming' && <option value="farming" disabled>Farming selected in header</option>}
      {runMode === 'navigation' && <option value="navigation" disabled>Navigation selected in header</option>}
      <option value="preview">Preview · no input</option><option value="live" disabled={s.capture_only}>Live combat · sends input</option>
    </select></label><p>{s.readiness[runMode === 'preview' ? 'preview' : 'combat'].reason}</p>
      {runMode === 'live' && <p className="warning-copy">Start gives you three seconds to focus the game. F8 cancels. Acknowledging an alarm never resumes combat.</p>}
    </Group><Group title="Current combat"><dl><div><dt>State</dt><dd>{s.state}</dd></div><div><dt>Last action</dt><dd>{s.last_action ?? 'none'}</dd></div>
      <div><dt>Target</dt><dd>{s.target?.kind ?? 'No target'}</dd></div></dl><p>{s.reason}</p></Group>
    <Group title="Potions during combat"><p>{s.sustain?.length ? `Combat may press: ${s.sustain.map(r => r.toUpperCase()).join(', ')}. Potions go before combat keys.` : 'Live combat presses a potion only when its bar is calibrated, its threshold is above zero and its probe is confirmed.'}</p>
      <p>An unreadable HUD for five seconds or an empty HP bar stops combat.</p></Group>
    <Group title="Attack ranges"><p>Existing attack tuning and low-MP fallback remain active. Visual range editing is not available yet.</p></Group>
  </>;
}

export function PotionsTool({ snapshot: s, client, act, selected, disabled, selectOnly, startInstruction }: ToolProps) {
  const [settings, setSettings] = useState(s.autopotter.settings);
  const update = (key: keyof typeof settings, value: string) => setSettings(previous => ({ ...previous, [key]: Number(value) }));
  return <><p className="tool-intro">Read visible HP/MP bars. Preview never sends potion keys.</p>
    <Group title="Resources"><div className="resource-grid">{(['hp', 'mp'] as const).map(resource => {
      const reading = s.autopotter.readings?.[resource];
      return <div key={resource}><span className="eyebrow">{resource.toUpperCase()}</span>
        <strong>{reading?.percent != null ? `${reading.percent}%` : '—'}</strong>
        <small>{reading?.percent != null ? `${reading.confidence.toFixed(2)} similarity` : s.autopotter.calibrated?.includes(resource) ? 'Waiting for readable HUD' : 'Not calibrated'}</small></div>;
    })}</div><p>{s.autopotter.enabled ? (s.autopotter.preview_only ? 'Preview · ' : 'Live · ') : 'Stopped · '}{s.autopotter.reason}</p>
    </Group><Group title="Thresholds"><label>HP threshold (%)<input type="number" min="0" max="95" value={settings.hp_threshold} onChange={e => update('hp_threshold', e.target.value)} /></label>
      <label>MP threshold (%)<input type="number" min="0" max="95" value={settings.mp_threshold} onChange={e => update('mp_threshold', e.target.value)} /></label>
      <label>Cooldown (seconds)<input type="number" min="0.5" max="30" step="0.1" value={settings.cooldown} onChange={e => update('cooldown', e.target.value)} /></label>
      <p>Zero disables that resource. Two low readings are required; HP takes priority.</p>
      <button disabled={disabled} onClick={() => void act(() => client.command('autopotter_settings', settings))}>Save thresholds</button>
    </Group><Group title="Potion mode"><div className="button-grid">
      <button disabled={disabled} onClick={() => void act(() => client.command('autopotter_start'))}>{selectOnly ? 'Select potion preview' : 'Start potion preview'}</button>
      <button disabled={disabled || s.capture_only || !s.readiness.potions.ready} onClick={() => void act(() => client.command('autopotter_live'))}>{selectOnly ? 'Select live potions' : 'Start live potions'}</button>
      {!selectOnly && <button disabled={disabled} onClick={() => void act(() => client.command('autopotter_stop'))}>Stop potions</button>}</div>
      {selectOnly && <p>{startInstruction ?? 'Selection sends no keys. Close settings and press F6 to turn the selected mode On.'}</p>}
      {!s.capture_only && <p>Live potions require readable calibrated bars and verified potion controls. Focus the game during the three-second countdown.</p>}
    </Group><Group title="HUD calibration"><p>Freeze a frame with full bars. Select one complete bar including its pale border, excluding numbers.</p>
      <div className="button-grid">{(['hp', 'mp'] as const).map(resource => <button key={resource} disabled={disabled}
        onClick={() => void act(() => client.command('autopotter_calibrate', { ...selected(), resource }))}>Calibrate {resource.toUpperCase()} bar</button>)}</div>
    </Group>
  </>;
}

export function Controls({ snapshot: s, client, act, disabled, selectOnly, startInstruction, bowman = false }: ToolProps & { bowman?: boolean }) {
  const active = s.active_probe;
  const blocker = s.capture_only || active ? '' : s.alarm?.active ? 'Acknowledge the active alarm first'
    : s.readiness.preview.ready ? '' : s.readiness.preview.reason;
  const actions = [...s.required_probes, ...s.optional_probes];
  const probe = (action: string) => {
    const gate = s.readiness[`probe:${action}`];
    return <div key={action}>
      <button disabled={disabled || s.capture_only || Boolean(active) || Boolean(blocker) || gate?.ready === false}
        onClick={() => void act(() => client.command('probe', { action }))}>{action.replaceAll('_', ' ')}</button>
      <span>{s.bindings[action]} · {s.probes[action]?.confirmed ? 'Verified' : s.required_probes.includes(action) ? 'Required' : 'Optional'}</span>
      {gate?.ready === false && !active && <small>{gate.reason}</small>}
    </div>;
  };
  return <Group title="Verify controls"><p>{selectOnly ? `${startInstruction ?? 'Select a probe, close settings and press F6 in game to test it.'} ` : ''}Each probe sends one bounded press after a three-second countdown. Focus the game and confirm only the observed effect. Saved confirmations remain tied to this layout and binding.</p>
    {s.capture_only && <p className="warning-copy">Capture-only session. Probes and gameplay output are locked.</p>}
    {blocker && <p className="warning-copy" role="alert">Probes blocked: {blocker}</p>}
    <div className="probe-list">{actions.filter(action => !bowman || ['attack', 'skill'].includes(action)).map(probe)}</div>
    {bowman && <details><summary>Movement and potion controls · {actions.filter(action => s.probes[action]?.confirmed).length} verified</summary>
      <div className="probe-list">{actions.filter(action => !['attack', 'skill'].includes(action)).map(probe)}</div>
      <p>Keep valid confirmations. Repeat only a changed or failed control.</p>
    </details>}
    {active && <div className="probe-active"><strong>{active.action.replaceAll('_', ' ')} · {active.phase.replaceAll('_', ' ')}</strong><p>{active.instruction}</p>
      {active.phase === 'awaiting_confirmation' && <button disabled={disabled} onClick={() => void act(() => client.command('confirm_probe', { id: active.id, generation: active.generation }))}>Confirm observed effect</button>}
      <button disabled={disabled} onClick={() => void act(() => client.command('reject_probe', { id: active.id, generation: active.generation }))}>Reject probe</button></div>}
    <details><summary>Bindings and saved probe details</summary><Data value={s.bindings} /><Data value={s.probes} /></details>
  </Group>;
}

export function SettingsTool(props: ToolProps) {
  const { snapshot: s, client, act, disabled, clear, selected } = props;
  const [windows, setWindows] = useState<WindowInfo[]>([]);
  const [windowId, setWindowId] = useState('');
  const [manual, setManual] = useState({ x: 0, y: 0, width: 1366, height: 768 });
  const refresh = () => act(async () => {
    const items = await client.command<WindowInfo[]>('windows');
    setWindows(items);
    setWindowId(previous => items.some(item => String(item.hwnd) === previous) ? previous : String(items.find(item => /maplestory/i.test(item.title))?.hwnd ?? ''));
    return undefined;
  });
  useEffect(() => { void refresh(); }, []);
  const changeCapture = (name: string, payload: () => Record<string, unknown> = () => ({})) => act(async () => {
    const result = await client.command(name, payload()); clear(); return result;
  });
  return <><p className="tool-intro">Occasional setup. Editing capture or calibration stops input.</p>
    <Group title="Game connection"><p>{s.window ? `${s.window.title} · ${s.window.client.width} × ${s.window.client.height}` : 'No game window connected.'}</p>
      <p className="reading">{s.calibration?.capture_verified ? 'Game view verified' : 'Waiting for capture verification'}</p>
      <button disabled={disabled} onClick={() => void changeCapture('connect_saved_window')}>Reconnect saved game</button>
      <label>Visible window<select value={windowId} onChange={e => setWindowId(e.target.value)}><option value="">Select a window…</option>{windows.map(item => <option key={item.hwnd} value={item.hwnd}>{item.title} · {item.client.width}×{item.client.height}</option>)}</select></label>
      <div className="button-grid"><button disabled={disabled} onClick={() => void refresh()}>Refresh windows</button>
        <button disabled={disabled || !windowId} onClick={() => void changeCapture('attach', () => ({ hwnd: Number(windowId) }))}>Attach window</button></div>
      <details><summary>Manual desktop region</summary><p>Physical pixels; negative origins support other monitors. Observation only: this source cannot arm input.</p>
        <div className="field-grid">{(['x', 'y', 'width', 'height'] as const).map(key => <label key={key}>{key}<input type="number" value={manual[key]} onChange={e => setManual(previous => ({ ...previous, [key]: Number(e.target.value) }))} /></label>)}</div>
        <button disabled={disabled} onClick={() => void changeCapture('manual', () => manual)}>Capture manual region</button></details>
    </Group><Group title="Game crop"><p>Use native 1× game pixels. Freeze the preview and select the rendered game, excluding window chrome and letterboxing.</p>
      <div className="button-grid"><button disabled={disabled} onClick={() => void changeCapture('crop', () => ({ ...selected() }))}>Apply selected crop</button>
        <button disabled={disabled} onClick={() => void changeCapture('reset_crop')}>Reset crop</button></div>
      <button disabled={disabled || !s.calibration || !s.width || s.calibrating} onClick={() => void act(() => client.command('confirm_capture'))}>Confirm game view manually</button>
    </Group><Controls {...props} /><Group title="Recordings"><p>Incident clips are automatic. Save a screenshot or recent clip from the preview toolbar; full recording is optional.</p>
      <button disabled={disabled} onClick={() => void act(() => client.command('record'))}>{s.recorder?.full ? 'Stop full recording' : 'Start full recording'}</button>
      <details><summary>Recorder details</summary><Data value={s.recorder ?? { recording: s.recording }} /></details>
    </Group><Group title="Session"><p>{s.capture_only ? 'Keyboard output is locked for this session. Recognition and previews remain available.' : 'Input-capable session. Capture and control verification are still required.'}</p>
      <div className="button-grid"><button disabled={disabled || !s.restart_available} onClick={() => void act(() => client.restart())}>Restart bot</button>
        <button disabled={disabled || !s.shutdown_available} onClick={() => void act(() => client.shutdown())}>Stop server</button></div>
      <p>Restart preserves saved settings and starts unarmed.</p><a className="quiet-link" href="/legacy" target="_blank" rel="noreferrer">Open legacy debugger ↗</a>
    </Group>
  </>;
}

export function DiagnosticsTool({ snapshot: s, client, act, disabled }: ToolProps) {
  return <><p className="tool-intro">Technical evidence and recent decisions, away from the everyday workspace.</p>
    <Group title="Capture health"><dl><div><dt>Capture FPS</dt><dd>{s.fps ?? '—'}</dd></div><div><dt>Latency</dt><dd>{s.latency_ms != null ? `${s.latency_ms} ms` : '—'}</dd></div><div><dt>Game focus</dt><dd>{s.focused ? 'Yes' : 'No'}</dd></div></dl>
      <button disabled={disabled || s.alarm.active} onClick={() => void act(() => client.command('restart_capture'))}>Restart capture worker</button>
      {s.alarm.active && <p>Acknowledge the alarm before restarting capture.</p>}</Group>
    <Group title="Detection failures">{s.failures?.length ? <ul>{s.failures.map((failure, index) => <li key={index}>{failure}</li>)}</ul> : <p>No detection failures.</p>}</Group>
    <Group title="Recent decisions"><ol className="history">{s.history.map((entry, index) => <li key={index}><time>{new Date(entry.time * 1000).toLocaleTimeString()}</time><span>{entry.reason}</span></li>)}</ol></Group>
    <Group title="Frame timing"><Data value={s.stage_timing ?? {}} /><Data value={s.encoder ?? {}} /></Group>
    <Group title="Action outcome"><Data value={s.action_outcome ?? {}} /></Group>
    <Group title="Identity"><Data value={{ schema: s.schema_version, session: s.session_id, frame: s.frame, epoch: s.command_epoch }} /></Group>
  </>;
}
