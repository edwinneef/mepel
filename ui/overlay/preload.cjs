const { contextBridge, ipcRenderer } = require('electron');
let dragging = false, lastInteractive = null;
const interactiveAt = event => Boolean(document.elementFromPoint(event.clientX, event.clientY)
  ?.closest('.editing-layout .overlay-panel, .editing-layout .overlay-hud, .editing-layout .terrain-inset, .editing-layout dialog[open], .hud-settings, .overlay-menu'));
const mouse = interactive => {
  if (interactive === lastInteractive) return;
  lastInteractive = interactive;
  ipcRenderer.send('overlay-mouse', interactive);
};
// Forwarded mouse moves still arrive while the transparent desktop is click-through.
window.addEventListener('mousemove', event => mouse(dragging || interactiveAt(event)));
window.addEventListener('pointerdown', event => { dragging = interactiveAt(event); mouse(dragging); }, true);
window.addEventListener('pointerup', event => { dragging = false; mouse(interactiveAt(event)); }, true);
window.addEventListener('pointercancel', () => { dragging = false; mouse(false); }, true);
window.addEventListener('blur', () => { dragging = false; mouse(false); });
ipcRenderer.on('overlay-event', (_event, value) => {
  if (value.type === 'panel') { dragging = false; lastInteractive = null; mouse(false); }
});
contextBridge.exposeInMainWorld('mapleOverlay', {
  companion: true,
  settings: open => ipcRenderer.invoke('overlay-settings', open),
  quit: () => ipcRenderer.invoke('overlay-quit'),
  heartbeat: () => ipcRenderer.send('overlay-paint'),
  batch: request => ipcRenderer.invoke('overlay-batch', request),
  interactive: rects => ipcRenderer.send('overlay-rects', rects),
  subscribe: callback => {
    const handler = (_event, value) => callback(value);
    ipcRenderer.on('overlay-event', handler);
    return () => ipcRenderer.removeListener('overlay-event', handler);
  },
});
