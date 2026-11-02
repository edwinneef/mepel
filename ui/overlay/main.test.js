// @vitest-environment node
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { expect, it, vi } from 'vitest';

function fakeChild() {
  const handlers = {};
  const stream = () => ({ on: (name, callback) => { handlers[`out:${name}`] = callback; } });
  return { handlers, stdout: stream(), stderr: stream(),
    on: (name, callback) => { handlers[name] = callback; } };
}

let cursor = { x: 0, y: 0 };
let engineStatus = {};
// Hands the overlay one request the way the engine queues a dashboard Start; returns its acknowledgement.
async function queue({ intervals, requests }, id, fields) {
  engineStatus = { batch_request: { id, ...fields } };
  await intervals[0]();
  engineStatus = {};
  await intervals[0]();
  return requests.map(request => request.body.batch_ack).filter(Boolean).find(ack => ack.id === id);
}
async function startOverlay(controllerReady = true) {
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
    __dirname: '/overlay', process: { env: {} }, Buffer, URL, AbortSignal,
    setInterval: callback => { intervals.push(callback); },
    fetch: async (url, options) => {
      if (options?.body) requests.push({ url, body: JSON.parse(options.body) });
      return { ok: true, text: async () => '<meta name="debug-token" content="token">',
        json: async () => ({ connected: true, controller_ready: controllerReady, ...engineStatus }) };
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

it('registers only emergency Stop and outline visibility shortcuts', async () => {
  const { shortcuts } = await startOverlay();
  expect([...shortcuts.keys()]).toEqual(['F8', 'F9']);
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
      '--minutes', '15', '--single']);
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
      '--run', '--focus', '--minutes', '1', '--circuit', 'lower-loop', '--revision', '2', '--consumables']);
    spawn.mock.results[1].value.handlers.close(0);
    expect(await queue(overlay, 9, { kind: 'single', area, minutes: 1 })).toEqual({ id: 9, started: true });
    expect(spawn.mock.calls[2][1]).toEqual(['-m', 'tools.prepared_farm_check', '--area', area,
      '--run', '--focus', '--minutes', '1', '--single']);
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
    engineStatus = { batch_request: { id: 3, kind: 'single', area: 'a'.repeat(32), minutes: 1 } };
    await intervals[0]();
    expect(spawn).toHaveBeenCalledTimes(1);
    expect(spawn.mock.calls[0][1]).toEqual(['-m', 'tools.prepared_farm_check', '--area', 'a'.repeat(32),
      '--run', '--focus', '--minutes', '1', '--single']);
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

it('registers the engine’s configured stop and drawings keys', async () => {
  try {
    engineStatus = { key_settings: { active: { emergency_key: 'f10', drawings: 'f11' } } };
    const { shortcuts } = await startOverlay();
    expect([...shortcuts.keys()].sort()).toEqual(['F10', 'F11']);
    engineStatus = { key_settings: { active: { emergency_key: 'ctrl' } } };  // never a non F-key
    const second = await startOverlay();
    expect([...second.shortcuts.keys()].sort()).toEqual(['F8', 'F9']);
  } finally { engineStatus = {}; }
});
