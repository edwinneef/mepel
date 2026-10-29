// @vitest-environment node
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { expect, it, vi } from 'vitest';

async function startOverlay() {
  const shortcuts = new Map(), requests = [];
  const win = {
    webContents: { send: vi.fn(), on: vi.fn(), setWindowOpenHandler: vi.fn() },
    setContentProtection: vi.fn(), setMenu: vi.fn(), on: vi.fn(),
    setIgnoreMouseEvents: vi.fn(), setFocusable: vi.fn(), show: vi.fn(),
    focus: vi.fn(), blur: vi.fn(), showInactive: vi.fn(),
    isDestroyed: () => false, getNativeWindowHandle: () => Buffer.alloc(8, 1),
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
  screen: { getAllDisplays: () => [{ bounds: { x: 0, y: 0, width: 1920, height: 1080 } }] },
  dialog: { showErrorBox: vi.fn() } };
  vm.runInNewContext(readFileSync(new URL('./main.cjs', import.meta.url), 'utf8'), {
    require: name => ({ electron, 'node:path': path,
      'node:crypto': { randomUUID: () => 'overlay-owner' }, 'node:fs/promises': {} })[name],
    __dirname: '/overlay', process: { env: {} }, Buffer, URL, AbortSignal,
    setInterval: vi.fn(),
    fetch: async (url, options) => {
      if (options?.body) requests.push({ url, body: JSON.parse(options.body) });
      return { ok: true, text: async () => '<meta name="debug-token" content="token">',
        json: async () => ({ connected: true }) };
    },
  });
  await started;
  return { win, construct, shortcuts, requests, electron };
}

it('starts Off with settings closed and click-through without activating the overlay', async () => {
  const { win, construct, requests, electron } = await startOverlay();
  expect(electron.dialog.showErrorBox).not.toHaveBeenCalled();
  expect(construct).toHaveBeenCalledWith(expect.objectContaining({ show: false, focusable: false }));
  expect(win.focus).not.toHaveBeenCalled();
  expect(win.show).not.toHaveBeenCalled();
  expect(win.showInactive).toHaveBeenCalled();
  expect(win.setIgnoreMouseEvents).toHaveBeenCalledWith(true, { forward: true });
  expect(requests.map(request => request.url)).toEqual([
    'http://127.0.0.1:8765/api/stop', 'http://127.0.0.1:8765/api/overlay',
  ]);
  expect(requests[1].body.panel).toBe(false);
  expect(win.webContents.send).toHaveBeenCalledWith('overlay-event', { type: 'panel', value: false });
});

it('activates settings only on explicit F7 and never resumes gameplay when closing', async () => {
  const { win, shortcuts, requests } = await startOverlay();
  shortcuts.get('F7')();
  await vi.waitFor(() => expect(win.focus).toHaveBeenCalledOnce());
  expect(requests.at(-1).body.panel).toBe(true);
  shortcuts.get('F7')();
  await vi.waitFor(() => expect(requests.at(-1).body.panel).toBe(false));
  expect(win.focus).toHaveBeenCalledOnce();
  expect(requests.every(request => /\/api\/(stop|overlay)$/.test(request.url))).toBe(true);
});
