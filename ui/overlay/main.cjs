const { app, BrowserWindow, globalShortcut, ipcMain, screen, dialog } = require('electron');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs/promises');
const { spawn } = require('node:child_process');

const port = Number(process.env.MAPLEBOT_PORT || 8765);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid engine port');
const base = `http://127.0.0.1:${port}`;
const owner = randomUUID();
let win, token, panel = false, quitting = false, lastPaint = 0, polling = false;
let session = null, lastBounds = '', transition = false, batch = null;
let controllerReady = false, gameFocused = false;
// Dashboard starts arrive through the companion heartbeat; each runs once through startBatch.
let batchReport = { running: false }, batchAck = null, handledRequest = null;
// The overlay is click-through except while the cursor is over its settings panel.
// The window is never focusable, so a click leaves the game focused.
let hovering = false, takingMouse = false;
function updateMouse() {
  if (!win || win.isDestroyed() || hovering === takingMouse) return;
  takingMouse = hovering;
  win.setIgnoreMouseEvents(!hovering, { forward: true });
  keepAboveGame();
}
function desktopBounds() {
  const displays = screen.getAllDisplays().map(display => display.bounds);
  const x = Math.min(...displays.map(rect => rect.x));
  const y = Math.min(...displays.map(rect => rect.y));
  return { x, y, width: Math.max(...displays.map(rect => rect.x + rect.width)) - x,
    height: Math.max(...displays.map(rect => rect.y + rect.height)) - y };
}
async function post(route, body) {
  const response = await fetch(`${base}/api/${route}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Debug-Token': token },
    body: JSON.stringify(body), signal: AbortSignal.timeout(1500),
  });
  const value = await response.json();
  if (!response.ok) {
    const error = new Error(value.error || `Engine ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return value;
}
const stop = () => post('stop', {}).catch(() => {});
/** Electron accelerators for the engine's active stop and drawings keys (F1-F12). */
async function activeKeys() {
  const fallback = { emergency_key: 'F8', drawings: 'F9' };
  try {
    const response = await fetch(`${base}/api/v1/status`, { signal: AbortSignal.timeout(1500) });
    const active = (await response.json())?.key_settings?.active ?? {};
    return Object.fromEntries(Object.entries(fallback).map(([name, key]) => {
      const value = String(active[name] ?? '');
      return [name, /^f([1-9]|1[0-2])$/.test(value) ? value.toUpperCase() : key];
    }));
  } catch { return fallback; }  // An older engine: the engine still polls its own stop key.
}
const send = (type, value) => { if (win && !win.isDestroyed()) win.webContents.send('overlay-event', { type, value }); };
const reportBatch = value => { batchReport = value; send('batch', value); };
const heartbeat = async open => {
  const ack = batchAck;
  const state = await post('overlay_companion', { owner, panel: open,
    hwnd: Number(win.getNativeWindowHandle().readBigUInt64LE()), batch: batchReport, ...(ack ? { batch_ack: ack } : {}) });
  if (ack && batchAck === ack) batchAck = null;
  controllerReady = state.controller_ready === true;
  send('controller', controllerReady);
  const request = state.batch_request;
  if (request && Number.isInteger(request.id) && request.id !== handledRequest) {
    // The batch launcher: validation, renderer freshness, controller check and
    // one-at-a-time all apply. The engine only queued the request.
    handledRequest = request.id;
    const { id, ...fields } = request;
    const result = await startBatch(fields);
    batchAck = { id, started: result.started === true, ...(result.reason ? { reason: result.reason } : {}) };
  }
  return state;
};
function keepAboveGame() {
  // Win32 show/click-through transitions can clear WS_EX_TOPMOST while Electron
  // still caches true. Force the native transition without activating the window.
  win.moveTop();
  win.setAlwaysOnTop(false);
  win.setAlwaysOnTop(true);
}
// One guarded batch at a time, from the dashboard: the same tool the start window runs,
// so its focus handoff, preflight, bounded session, result file and alarm stay identical.
async function startBatch(request) {
  const kind = request?.kind, area = String(request?.area ?? '');
  if (!['learn', 'single'].includes(kind) || !/^[a-f0-9]{32}$/.test(area)) {
    return { started: false, reason: 'Invalid batch request' };
  }
  if (batch) return { started: false, reason: 'A batch is already running' };
  const circuit = request?.circuit;
  if (kind === 'learn' && (!circuit || !/^[A-Za-z0-9_-]{1,80}$/.test(circuit.id)
      || !Number.isInteger(circuit.revision) || circuit.revision < 1
      || ![1, 15].includes(request.minutes))) {
    return { started: false, reason: 'Choose a saved circuit revision and a 1 or 15 minute run' };
  }
  // One platform takes the same 1 or 15 minute choice; a request without one gets 15.
  const minutes = kind === 'single' && request?.minutes === undefined ? 15 : request?.minutes;
  if (kind === 'single' && ![1, 15].includes(minutes)) {
    return { started: false, reason: 'Choose a 1 or 15 minute run' };
  }
  if (Date.now() - lastPaint >= 1200) {
    return { started: false, reason: 'Overlay renderer is not fresh' };
  }
  await heartbeat(false);
  if (!controllerReady) {
    return { started: false, reason: 'Connect the browser dashboard before starting a batch' };
  }
  if (batch) return { started: false, reason: 'A batch is already running' };
  const root = path.resolve(__dirname, '..', '..');
  const args = ['-m', 'tools.prepared_farm_check', '--area', area, '--run', '--focus',
    '--minutes', String(minutes),
    ...(kind === 'single' ? ['--single'] : ['--circuit', circuit.id,
      '--revision', String(circuit.revision), '--consumables'])];
  let output = '';
  const child = spawn(path.join(root, '.venv', 'Scripts', 'python.exe'), args,
    { cwd: root, windowsHide: true });
  batch = child;
  const read = chunk => {
    output = (output + chunk.toString()).slice(-4000);
    reportBatch({ running: true, kind, line: output.trim().split(/\r?\n/).pop() });
  };
  child.stdout.on('data', read);
  child.stderr.on('data', read);
  child.on('error', error => {
    if (batch === child) batch = null;
    reportBatch({ running: false, kind, code: -1, output: error.message });
  });
  child.on('close', code => {
    if (batch === child) batch = null;
    reportBatch({ running: false, kind, code, output });
  });
  reportBatch({ running: true, kind, line: 'Starting one guarded batch; restoring game focus...' });
  return { started: true };
}
async function settings(open) {
  if (open) return; // The native window is outlines only; settings stay in the dashboard.
  if (transition || !win || win.isDestroyed()) return;
  transition = true;
  try {
    // Opening is acknowledged by the engine only after keys have been released.
    await heartbeat(open);
    panel = open;
    win.setIgnoreMouseEvents(true, { forward: true });
    win.setFocusable(open);
    if (open) { win.show(); win.focus(); } else { win.blur(); win.showInactive(); }
    // Click-through/show transitions can clear the native topmost flag on Windows.
    keepAboveGame();
    send('panel', open);
  } catch (error) {
    send('error', error.message);
    if (error.status >= 400 && error.status < 500) app.quit();
  }
  finally { transition = false; }
}
async function poll() {
  if (polling || quitting) return;
  polling = true;
  try {
    const response = await fetch(`${base}/api/v1/status`, { signal: AbortSignal.timeout(1000) });
    if (!response.ok) throw new Error('Engine unavailable');
    const status = await response.json();
    if (session && status.session_id !== session) {
      await stop();
      app.quit(); // Relaunch explicitly: never reconnect a queued action across sessions.
      return;
    }
    session = status.session_id;
    // Read session identity before using the token: restarts rotate credentials.
    // A stalled renderer stops renewing companion health; dashboard control is separate.
    if (Date.now() - lastPaint < 1200 && !transition) {
      const lease = await heartbeat(panel);
      if (lease.close_requested && panel) await settings(false);
    }
    const desktop = desktopBounds();
    const key = JSON.stringify(desktop);
    if (key !== lastBounds) { win.setBounds(desktop); lastBounds = key; }
    const crop = status.calibration?.crop;
    const client = status.window?.client;
    if (client && crop && status.preview_frame?.available) {
      const rect = { x: client.x + crop.x, y: client.y + crop.y,
        width: crop.width, height: crop.height };
      const bounds = screen.screenToDipRect(null, rect);
      send('game-bounds', { x: bounds.x - desktop.x, y: bounds.y - desktop.y,
        width: bounds.width, height: bounds.height, visible: Boolean(status.focused || panel) });
    } else send('game-bounds', null);
    if (!panel && !win.isVisible()) {
      win.showInactive();
      keepAboveGame();
    } else if (status.focused === true && !gameFocused && !panel) {
      // Windows can drop the topmost flag of a visible overlay (for example when a browser
      // opens over it), and nothing else restores it. Raise it again when the game regains focus.
      keepAboveGame();
    }
    gameFocused = status.focused === true;
  } catch (error) {
    controllerReady = false;
    send('controller', false);
    send('error', error.message);
    send('game-bounds', null);
    if (error.status >= 400 && error.status < 500) app.quit();
  } finally { polling = false; }
}
if (!app.requestSingleInstanceLock()) app.quit();
else app.whenReady().then(async () => {
  try {
    const html = await (await fetch(base, { signal: AbortSignal.timeout(3000) })).text();
    token = html.match(/name="debug-token" content="([^"]+)"/)?.[1];
    if (!token) throw new Error('Start the MapleBot engine before opening the overlay.');
    await stop();
    const area = desktopBounds();
    win = new BrowserWindow({ ...area, transparent: true, frame: false, show: false, focusable: false,
      alwaysOnTop: true, skipTaskbar: false, title: 'Maple Overlay',
      webPreferences: { preload: path.join(__dirname, 'preload.cjs'), sandbox: true,
        contextIsolation: true, nodeIntegration: false, backgroundThrottling: false } });
    win.setContentProtection(true);
    win.setMenu(null);
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (event, url) => {
      if (new URL(url).origin !== base) event.preventDefault();
    });
    const own = event => event.sender === win.webContents;
    ipcMain.on('overlay-paint', event => { if (own(event)) lastPaint = Date.now(); });
    ipcMain.on('overlay-mouse', (event, interactive) => {
      if (own(event) && typeof interactive === 'boolean') { hovering = interactive; updateMouse(); }
    });
    ipcMain.handle('overlay-settings', (event, open) => own(event) && settings(Boolean(open)));
    ipcMain.handle('overlay-quit', event => { if (own(event)) app.quit(); });
    win.webContents.on('render-process-gone', () => { void stop(); app.quit(); });
    win.on('unresponsive', () => { void stop(); });
    win.on('close', () => { void stop(); });
    for (let attempt = 0; ; attempt += 1) {
      try {
        await win.loadURL(`${base}/?overlay=1`);
        break;
      } catch (error) {
        if (quitting || win.isDestroyed()) return;
        if (attempt >= 2 || !/ERR_FAILED|ERR_CONNECTION_REFUSED|ERR_CONNECTION_RESET/.test(error.message)) throw error;
        // Startup only: no lease or hotkeys exist yet. A transient engine/renderer
        // restart may abort the first navigation; never carry an action across it.
        await new Promise(resolve => setTimeout(resolve, 1000));
        const html = await (await fetch(base, { signal: AbortSignal.timeout(3000) })).text();
        token = html.match(/name="debug-token" content="([^"]+)"/)?.[1];
        if (!token) throw error;
        await stop();
      }
    }
    // DWM must know the visible layered window before the engine can verify affinity.
    win.showInactive();
    win.setContentProtection(true);
    await settings(false); // Startup leaves the game focused; F7 explicitly opens settings.
    if (process.env.MAPLEBOT_OVERLAY_DIAGNOSTICS) {
      const directory = path.resolve(process.env.MAPLEBOT_OVERLAY_DIAGNOSTICS);
      setTimeout(async () => {
        try {
          await fs.mkdir(directory, { recursive: true });
          await fs.writeFile(path.join(directory, 'overlay.png'), (await win.webContents.capturePage()).toPNG());
          await fs.writeFile(path.join(directory, 'window.json'), JSON.stringify({
            bounds: win.getBounds(), hwnd: win.getNativeWindowHandle().readBigUInt64LE().toString(),
            panel, session, companion: true, controllerReady, contentProtected: win.isContentProtected(),
          }, null, 2));
          await settings(false);
          await fs.writeFile(path.join(directory, 'click-through.json'), JSON.stringify({
            hwnd: win.getNativeWindowHandle().readBigUInt64LE().toString(),
            focusable: win.isFocusable(), panel, contentProtected: win.isContentProtected(),
            hotkeys: ['F6', 'F7', 'F8', 'F9'].map(key => [key, globalShortcut.isRegistered(key)]),
          }, null, 2));
          await settings(true);
        } catch (error) { console.error(error); }
      }, 3000);
    }
    // Hotkeys come from the engine's active keys (config.toml, applied at engine start). The
    // overlay quits on a new engine session, so it never re-binds keys while it runs.
    const keys = await activeKeys();
    for (const [key, action] of [
      // Always deliver the key. The renderer reports blockers and the engine
      // retains its authoritative focus/input gates. Off must never be ignored.
      [keys.emergency_key, () => { void stop(); send('off'); }],
      [keys.drawings, () => send('layers')],
    ]) if (!globalShortcut.register(key, action)) throw new Error(`${key} is already registered by another app`);
    setInterval(poll, 300);
  } catch (error) {
    await stop();
    if (!quitting) dialog.showErrorBox('Maple Overlay', error.message);
    app.quit();
  }
});
app.on('second-instance', () => { app.relaunch(); app.quit(); });
app.on('before-quit', event => {
  if (!quitting && token) {
    event.preventDefault(); quitting = true;
    void stop().finally(() => app.quit());
  }
});
app.on('will-quit', () => globalShortcut.unregisterAll());
