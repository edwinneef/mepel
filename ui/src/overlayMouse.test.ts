import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { expect, it, vi } from 'vitest';

function preload() {
  const handlers: Record<string, (event: unknown) => void> = {};
  const ipc: Record<string, (event: unknown, value: unknown) => void> = {};
  const send = vi.fn();
  let inside = false;
  runInNewContext(readFileSync('overlay/preload.cjs', 'utf8'), {
    require: () => ({ contextBridge: { exposeInMainWorld: vi.fn() },
      ipcRenderer: { send, on: (name: string, handler: typeof ipc[string]) => { ipc[name] = handler; } } }),
    window: { addEventListener: (name: string, handler: typeof handlers[string]) => { handlers[name] = handler; } },
    document: { elementFromPoint: () => ({ closest: () => inside ? {} : null }) },
  });
  return { send, handlers, ipc, inside: (value: boolean) => { inside = value; } };
}

it('lets desktop clicks pass through and enables only hovered panels', () => {
  const p = preload();
  p.handlers.mousemove({ clientX: 10, clientY: 20 });
  expect(p.send).toHaveBeenLastCalledWith('overlay-mouse', false);
  p.inside(true);
  p.handlers.mousemove({ clientX: 20, clientY: 30 });
  expect(p.send).toHaveBeenLastCalledWith('overlay-mouse', true);
  p.inside(false);
  p.handlers.mousemove({ clientX: 10, clientY: 20 });
  expect(p.send).toHaveBeenLastCalledWith('overlay-mouse', false);
});

it('retains a panel drag outside its bounds and releases on pointer-up or settings changes', () => {
  const p = preload();
  p.inside(true);
  p.handlers.pointerdown({ clientX: 20, clientY: 30 });
  p.inside(false);
  p.handlers.mousemove({ clientX: 1000, clientY: 20 });
  expect(p.send).toHaveBeenLastCalledWith('overlay-mouse', true);
  p.handlers.pointerup({ clientX: 1000, clientY: 20 });
  expect(p.send).toHaveBeenLastCalledWith('overlay-mouse', false);
  p.inside(true);
  p.handlers.pointerdown({ clientX: 20, clientY: 30 });
  p.ipc['overlay-event']({}, { type: 'panel', value: false });
  expect(p.send).toHaveBeenLastCalledWith('overlay-mouse', false);
});
