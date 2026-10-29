const { app, BrowserWindow, globalShortcut, ipcMain, screen, dialog } = require('electron');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs/promises');

const port = Number(process.env.MAPLEBOT_PORT || 8765);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid engine port');
const base = `http://127.0.0.1:${port}`;
const owner = randomUUID();
let win, token, panel = false, quitting = false, lastPaint = 0, polling = false;
let session = null, lastBounds = '', transition = false;
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
  if (!response.ok) throw new Error(value.error || `Engine ${response.status}`);
  return value;
}
const stop = () => post('stop', {}).catch(() => {});
const send = (type, value) => { if (win && !win.isDestroyed()) win.webContents.send('overlay-event', { type, value }); };
const heartbeat = open => post('overlay', { owner, panel: open,
  hwnd: Number(win.getNativeWindowHandle().readBigUInt64LE()) });
async function settings(open) {
  if (transition || !win || win.isDestroyed()) return;
  transition = true;
  try {
    // Opening is acknowledged by the engine only after keys have been released.
    await heartbeat(open);
    panel = open;
    win.setIgnoreMouseEvents(true, { forward: true });
    win.setFocusable(open);
    if (open) { win.show(); win.focus(); } else { win.blur(); win.showInactive(); }
    send('panel', open);
  } catch (error) { send('error', error.message); }
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
    // A stalled renderer also loses its input lease.
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
    if (!panel) win.showInactive();
  } catch (error) {
    send('error', error.message);
    send('game-bounds', null);
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
      if (own(event) && typeof interactive === 'boolean') {
        win.setIgnoreMouseEvents(!(panel && interactive), { forward: true });
      }
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
            panel, session, contentProtected: win.isContentProtected(),
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
    for (const [key, action] of [
      // Always deliver the key. The renderer reports blockers and the engine
      // retains its authoritative focus/input gates. Off must never be ignored.
      ['F6', () => send('toggle')],
      ['F7', () => void settings(!panel)],
      ['F8', () => { void stop(); send('off'); }],
      ['F9', () => send('layers')],
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
