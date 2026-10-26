const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('mapleOverlay', {
  settings: open => ipcRenderer.invoke('overlay-settings', open),
  quit: () => ipcRenderer.invoke('overlay-quit'),
  heartbeat: () => ipcRenderer.send('overlay-paint'),
  subscribe: callback => {
    const handler = (_event, value) => callback(value);
    ipcRenderer.on('overlay-event', handler);
    return () => ipcRenderer.removeListener('overlay-event', handler);
  },
});
