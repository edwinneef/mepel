// @vitest-environment node
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { expect, it, vi } from 'vitest';

function fakeChild() {
  const handlers = {};
  const stream = () => ({ on: (name, callback) => { handlers[`out:${name}`] = callback; } });
  return { handlers, kill: vi.fn(), stdout: stream(), stderr: stream(),
    on: (name, callback) => { handlers[name] = callback; } };
}

let cursor = { x: 0, y: 0 };
let engineStatus = {};
const authorization = id => ({ id, session_id: 'session-a', owner: 'dashboard-owner', epoch: 1, nonce: `nonce-${id}` });
const authArgs = id => ['--endpoint', 'http://127.0.0.1:8765', '--expected-session', 'session-a',
  '--batch-token', JSON.stringify(authorization(id))];
// Hands the overlay one request the way the engine queues a dashboard Start; returns its acknowledgement.
async function queue({ intervals, requests }, id, fields) {
  engineStatus = { batch_request: { id, token: authorization(id), ...fields } };
  await intervals[0]();
  engineStatus = {};
  await intervals[0]();
  return requests.map(request => request.body.batch_ack).filter(Boolean).find(ack => ack.id === id);
}
async function startOverlay(controllerReady = true, options = {}) {
  const shortcuts = new Map(), requests = [], intervals = [];
  const spawn = vi.fn(() => fakeChild());
  const win = {
    webContents: { send: vi.fn(), on: vi.fn(), setWindowOpenHandler: vi.fn() },
    setContentProtection: vi.fn(), setMenu: vi.fn(), on: vi.fn(),
    setIgnoreMouseEvents: vi.fn(), setFocusable: vi.fn(), show: vi.fn(),
    focus: vi.fn(), blur: vi.fn(), showInactive: vi.fn(), setAlwaysOnTop: vi.fn(), moveTop: vi.fn(),
    setBounds: vi.fn(),
    isDestroyed: () => false, isVisible: () => true,
    getNativeWindowHandle: () => Buffer.alloc(8, 1), getBounds: () => ({ x: 0, y: 0, width: 1920, height: 1080 }),
    loadURL: vi.fn(async () => {}),
  };
  const construct = vi.fn();
  let started;
  const app = { requestSingleInstanceLock: () => true,
    whenReady: () => ({ then: callback => { started = callback(); return started; } }),
    on: vi.fn(), quit: vi.fn() };
  const electron = { app, BrowserWindow: class {
    constructor(options) { construct(options); return win; }
  }, globalShortcut: { register: (key, action) => { shortcuts.set(key, action); return true; } },
  ipcMain: { on: vi.fn(), handle: vi.fn() },
  screen: { getAllDisplays: () => [{ bounds: { x: 0, y: 0, width: 1920, height: 1080 } }],
    getCursorScreenPoint: () => cursor },
  dialog: { showErrorBox: vi.fn() } };
  vm.runInNewContext(readFileSync(new URL('./main.cjs', import.meta.url), 'utf8'), {
    require: name => ({ electron, 'node:path': path,
      'node:crypto': { randomUUID: () => 'overlay-owner' }, 'node:fs/promises': {},
      'node:child_process': { spawn } })[name],
    __dirname: '/overlay', process: { env: options.env ?? {} }, Buffer, URL, AbortSignal,
    setInterval: callback => { intervals.push(callback); },
    fetch: async (url, request) => {
      if (request?.body) requests.push({ url, body: JSON.parse(request.body) });
      await options.beforeFetch?.(url, request);
      return { ok: true, text: async () => '<meta name="debug-token" content="token">',
        json: async () => ({ connected: true, session_id: 'session-a', controller_ready: controllerReady,
          input_state: { enabled: false, held_keys: [] }, ...engineStatus }) };
    },
  });
  await started;
  return { win, construct, shortcuts, requests, electron, intervals, spawn };
}

it('starts Off with settings closed and click-through without activating the overlay', async () => {
  const { win, construct, requests, electron } = await startOverlay();
  expect(electron.dialog.showErrorBox).not.toHaveBeenCalled();
  expect(construct).toHaveBeenCalledWith(expect.objectContaining({ show: false, focusable: false }));
  expect(win.focus).not.toHaveBeenCalled();
  expect(win.show).not.toHaveBeenCalled();
  expect(win.showInactive).toHaveBeenCalled();
  expect(win.setAlwaysOnTop.mock.invocationCallOrder.at(-1))
    .toBeGreaterThan(win.showInactive.mock.invocationCallOrder.at(-1));
  expect(win.moveTop).toHaveBeenCalled();
  expect(win.setIgnoreMouseEvents).toHaveBeenCalledWith(true, { forward: true });
  expect(requests.map(request => request.url)).toEqual([
    'http://127.0.0.1:8765/api/stop', 'http://127.0.0.1:8765/api/overlay_companion',
  ]);
  expect(requests[1].body.panel).toBe(false);
  expect(win.webContents.send).toHaveBeenCalledWith('overlay-event', { type: 'panel', value: false });
});

it('registers only the emergency Stop shortcut; the engine reads F6 and F9 itself', async () => {
  const { shortcuts, win, requests } = await startOverlay();
  expect([...shortcuts.keys()]).toEqual(['F8']);
  shortcuts.get('F8')();
  expect(requests.at(-1).url).toBe('http://127.0.0.1:8765/api/stop');
  expect(win.webContents.send).toHaveBeenLastCalledWith('overlay-event', { type: 'off', value: undefined });
});

it('raises the visible overlay above the game again each time the game regains focus', async () => {
  const { win, intervals } = await startOverlay();
  try {
    const raised = () => win.moveTop.mock.calls.length;
    const before = raised();
    engineStatus = { focused: true };
    await intervals[0]();
    expect(raised()).toBe(before + 1);
    await intervals[0]();  // still focused: no repeated Win32 transitions
    expect(raised()).toBe(before + 1);
    engineStatus = { focused: false };
    await intervals[0]();
    engineStatus = { focused: true };
    await intervals[0]();
    expect(raised()).toBe(before + 2);
    expect(win.setAlwaysOnTop.mock.calls.slice(-2)).toEqual([[false], [true]]);
  } finally { engineStatus = {}; }
});

it('takes the mouse only while hovering its panel and refuses native settings requests', async () => {
  const { win, requests, electron } = await startOverlay();
  const mouse = electron.ipcMain.on.mock.calls.find(([name]) => name === 'overlay-mouse')[1];
  mouse({ sender: win.webContents }, true);
  expect(win.setIgnoreMouseEvents).toHaveBeenLastCalledWith(false, { forward: true });
  mouse({ sender: win.webContents }, false);
  expect(win.setIgnoreMouseEvents).toHaveBeenLastCalledWith(true, { forward: true });
  mouse({ sender: {} }, true);  // another renderer cannot make the overlay take the mouse
  expect(win.setIgnoreMouseEvents).toHaveBeenLastCalledWith(true, { forward: true });
  const settings = electron.ipcMain.handle.mock.calls.find(([name]) => name === 'overlay-settings')[1];
  await settings({ sender: win.webContents }, true);
  expect(requests.at(-1).body.panel).toBe(false);
  expect(win.focus).not.toHaveBeenCalled();
  await settings({ sender: win.webContents }, false);
  expect(requests.at(-1).body.panel).toBe(false);
  expect(win.setFocusable).toHaveBeenLastCalledWith(false);
  expect(win.setAlwaysOnTop).toHaveBeenLastCalledWith(true);
  expect(win.setAlwaysOnTop.mock.calls.slice(-2)).toEqual([[false], [true]]);
});

it('keeps a visible overlay shown without repeating Win32 show transitions on every poll', async () => {
  const { win, intervals } = await startOverlay();
  const shown = win.showInactive.mock.calls.length;
  await intervals[0]();
  await intervals[0]();
  expect(win.showInactive).toHaveBeenCalledTimes(shown);
  expect(win.setAlwaysOnTop.mock.calls.slice(-2)).toEqual([[false], [true]]);
  const raised = win.setAlwaysOnTop.mock.invocationCallOrder.at(-1);
  expect(raised).toBeGreaterThan(win.moveTop.mock.invocationCallOrder.at(-1));
});


it('starts one guarded dashboard batch at a time, validating the request', async () => {
  const overlay = await startOverlay();
  const { win, electron, spawn } = overlay;
  electron.ipcMain.on.mock.calls.find(([name]) => name === 'overlay-paint')[1]({ sender: win.webContents });
  const area = 'a'.repeat(32);
  try {
    expect((await queue(overlay, 1, { kind: 'learn', area: '../x' })).started).toBe(false);
    expect((await queue(overlay, 2, { kind: 'jump', area })).started).toBe(false);
    expect(spawn).not.toHaveBeenCalled();
    expect(await queue(overlay, 3, { kind: 'single', area })).toEqual({ id: 3, started: true });
    expect(spawn.mock.calls[0][1]).toEqual(['-m', 'tools.prepared_farm_check', '--area', area, '--run', '--focus',
      '--minutes', '15', ...authArgs(3), '--single']);
    expect((await queue(overlay, 4, { kind: 'learn', area })).reason).toBe('A batch is already running');
    const child = spawn.mock.results[0].value;
    child.handlers['out:data'](Buffer.from('{"outcome": "nothing_left"}\n'));
    child.handlers.close(0);
    expect(win.webContents.send).toHaveBeenLastCalledWith('overlay-event', { type: 'batch',
      value: { running: false, kind: 'single', code: 0, output: '{"outcome": "nothing_left"}\n' } });
    expect((await queue(overlay, 5, { kind: 'learn', area })).started).toBe(false);
    expect((await queue(overlay, 6, { kind: 'single', area, minutes: 7 })).started).toBe(false);
    expect((await queue(overlay, 7, { kind: 'learn', area,
      circuit: { id: '../x', revision: 2 }, minutes: 1 })).started).toBe(false);
    expect(await queue(overlay, 8, { kind: 'learn', area,
      circuit: { id: 'lower-loop', revision: 2 }, minutes: 1 })).toEqual({ id: 8, started: true });
    expect(spawn.mock.calls[1][1]).toEqual(['-m', 'tools.prepared_farm_check', '--area', area,
      '--run', '--focus', '--minutes', '1', ...authArgs(8), '--circuit', 'lower-loop', '--revision', '2', '--consumables']);
    spawn.mock.results[1].value.handlers.close(0);
    expect(await queue(overlay, 9, { kind: 'single', area, minutes: 1 })).toEqual({ id: 9, started: true });
    expect(spawn.mock.calls[2][1]).toEqual(['-m', 'tools.prepared_farm_check', '--area', area,
      '--run', '--focus', '--minutes', '1', ...authArgs(9), '--single']);
  } finally { engineStatus = {}; }
});

it('registers only companion health and refuses batch input without a live dashboard controller', async () => {
  const { win, electron, requests, spawn, intervals } = await startOverlay(false);
  expect(requests.some(request => request.url.endsWith('/api/overlay'))).toBe(false);
  expect(requests.some(request => request.url.endsWith('/api/dashboard'))).toBe(false);
  expect(requests.some(request => request.url.endsWith('/api/overlay_companion'))).toBe(true);
  electron.ipcMain.on.mock.calls.find(([name]) => name === 'overlay-paint')[1]({ sender: win.webContents });
  try {
    expect(await queue({ intervals, requests }, 1, { kind: 'learn', area: 'a'.repeat(32),
      circuit: { id: 'lower-loop', revision: 2 }, minutes: 1 }))
      .toEqual({ id: 1, started: false, reason: 'Connect the browser dashboard before starting a batch' });
  } finally { engineStatus = {}; }
  expect(spawn).not.toHaveBeenCalled();
  expect(win.webContents.send).toHaveBeenCalledWith('overlay-event', { type: 'controller', value: false });
});

it('runs a dashboard batch request from the companion heartbeat once, through the same launcher', async () => {
  try {
    const { win, electron, spawn, intervals, requests } = await startOverlay();
    electron.ipcMain.on.mock.calls.find(([name]) => name === 'overlay-paint')[1]({ sender: win.webContents });
    engineStatus = { batch_request: { id: 3, token: authorization(3), kind: 'single', area: 'a'.repeat(32), minutes: 1 } };
    await intervals[0]();
    expect(spawn).toHaveBeenCalledTimes(1);
    expect(spawn.mock.calls[0][1]).toEqual(['-m', 'tools.prepared_farm_check', '--area', 'a'.repeat(32),
      '--run', '--focus', '--minutes', '1', ...authArgs(3), '--single']);
    await intervals[0]();  // the engine still lists it until the acknowledgement arrives
    expect(spawn).toHaveBeenCalledTimes(1);
    const sent = requests.filter(r => r.url.endsWith('/api/overlay_companion')).map(r => r.body);
    expect(sent.some(body => body.batch_ack?.id === 3 && body.batch_ack.started === true)).toBe(true);
    expect(sent.at(-1).batch).toMatchObject({ running: true, kind: 'single' });
    // An invalid queued request is refused by the launcher and acknowledged as not started.
    engineStatus = { batch_request: { id: 4, kind: 'jump', area: 'a'.repeat(32), minutes: 1 } };
    spawn.mock.results[0].value.handlers.close(0);
    await intervals[0]();
    await intervals[0]();
    expect(spawn).toHaveBeenCalledTimes(1);
    const last = requests.filter(r => r.url.endsWith('/api/overlay_companion')).map(r => r.body);
    expect(last.some(body => body.batch_ack?.id === 4 && body.batch_ack.started === false)).toBe(true);
  } finally { engineStatus = {}; }
});

it('registers the engine’s configured stop key', async () => {
  try {
    engineStatus = { key_settings: { active: { emergency_key: 'f10', drawings: 'f11' } } };
    const { shortcuts } = await startOverlay();
    expect([...shortcuts.keys()]).toEqual(['F10']);
    engineStatus = { key_settings: { active: { emergency_key: 'ctrl' } } };  // never a non F-key
    const second = await startOverlay();
    expect([...second.shortcuts.keys()]).toEqual(['F8']);
  } finally { engineStatus = {}; }
});


it.each(['overlay_companion', 'batch_heartbeat'])('F8 cancels launch while awaiting %s', async route => {
  let release, entered;
  const waiting = new Promise(resolve => { entered = resolve; });
  let armed = false, companions = 0;
  const overlay = await startOverlay(true, { beforeFetch: async url => {
    if (!armed || !url.endsWith(`/api/${route}`)) return;
    if (route === 'overlay_companion' && ++companions === 1) return;
    armed = false;
    entered();
    await new Promise(resolve => { release = resolve; });
  } });
  overlay.electron.ipcMain.on.mock.calls.find(([name]) => name === 'overlay-paint')[1]({ sender: overlay.win.webContents });
  armed = true;
  const launching = queue(overlay, 31, { kind: 'single', area: 'a'.repeat(32), minutes: 1 });
  await waiting;
  overlay.shortcuts.get('F8')();
  release();
  expect((await launching).started).toBe(false);
  expect(overlay.spawn).not.toHaveBeenCalled();
});

it('passes the initiating endpoint and session and rejects mismatched authorization', async () => {
  const overlay = await startOverlay(true, { env: { MAPLEBOT_PORT: '8877' } });
  overlay.electron.ipcMain.on.mock.calls.find(([name]) => name === 'overlay-paint')[1]({ sender: overlay.win.webContents });
  expect((await queue(overlay, 40, { kind: 'single', area: 'a'.repeat(32),
    token: { ...authorization(40), session_id: 'other-engine' } })).started).toBe(false);
  expect(overlay.spawn).not.toHaveBeenCalled();
  expect((await queue(overlay, 41, { kind: 'single', area: 'a'.repeat(32) })).started).toBe(true);
  const args = overlay.spawn.mock.calls[0][1];
  expect(args[args.indexOf('--endpoint') + 1]).toBe('http://127.0.0.1:8877');
  expect(args[args.indexOf('--expected-session') + 1]).toBe('session-a');
  expect(JSON.parse(args[args.indexOf('--batch-token') + 1])).toEqual(authorization(41));
});

it('cancels the associated engine batch on runner failure and records release evidence', async () => {
  const overlay = await startOverlay();
  overlay.electron.ipcMain.on.mock.calls.find(([name]) => name === 'overlay-paint')[1]({ sender: overlay.win.webContents });
  await queue(overlay, 51, { kind: 'single', area: 'a'.repeat(32) });
  overlay.spawn.mock.results[0].value.handlers.close(1);
  await vi.waitFor(() => expect(overlay.requests.some(r => r.url.endsWith('/batch_cancel'))).toBe(true));
  await vi.waitFor(() => expect(overlay.win.webContents.send).toHaveBeenLastCalledWith('overlay-event', {
    type: 'batch', value: expect.objectContaining({ running: false, code: 1,
      output: expect.stringContaining('Engine input disabled; no held keys') }),
  }));
  expect(overlay.requests.find(r => r.url.endsWith('/batch_cancel')).body)
    .toEqual({ token: authorization(51), failure: true });
});

it('kills only its child on Stop and ignores stale child completion after a new launch', async () => {
  const overlay = await startOverlay();
  overlay.electron.ipcMain.on.mock.calls.find(([name]) => name === 'overlay-paint')[1]({ sender: overlay.win.webContents });
  await queue(overlay, 61, { kind: 'single', area: 'a'.repeat(32) });
  const old = overlay.spawn.mock.results[0].value;
  overlay.shortcuts.get('F8')();
  expect(old.kill).toHaveBeenCalledOnce();
  await queue(overlay, 62, { kind: 'single', area: 'a'.repeat(32) });
  const sends = overlay.win.webContents.send.mock.calls.length;
  old.handlers.close(1);
  old.handlers.error(new Error('old child'));
  expect(overlay.win.webContents.send.mock.calls.length).toBe(sends);
  expect(overlay.requests.some(r => r.url.endsWith('/batch_cancel'))).toBe(false);
});
