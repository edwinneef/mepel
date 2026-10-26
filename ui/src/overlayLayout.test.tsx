import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useOverlayLayout } from './overlayLayout';

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

function Panels() {
  const layout = useOverlayLayout(true);
  return <><section data-testid="hud" style={layout.position('hud', { x: 14, y: 14 })}>
    <header {...layout.handlers('hud')}>Move HUD</header></section>
    <svg data-testid="world" style={{ position: 'fixed', left: 34, top: 57, width: 1366, height: 768 }} />
    <button onClick={layout.reset}>Reset positions</button></>;
}
it('moves the HUD outside the game, remembers it and leaves world geometry anchored', () => {
  vi.stubGlobal('PointerEvent', MouseEvent);
  vi.stubGlobal('innerWidth', 2560);
  vi.stubGlobal('innerHeight', 1440);
  const view = render(<Panels />);
  const handle = screen.getByText('Move HUD');
  handle.setPointerCapture = vi.fn();
  fireEvent.pointerDown(handle, { button: 0, clientX: 20, clientY: 20 });
  fireEvent.pointerMove(handle, { clientX: 1520, clientY: 220 });
  fireEvent.pointerUp(handle);
  expect(screen.getByTestId('hud').style.left).toBe('1500px');
  expect(screen.getByTestId('world').style.left).toBe('34px');
  view.unmount();
  render(<Panels />);
  expect(screen.getByTestId('hud').style.left).toBe('1500px');
  fireEvent.click(screen.getByText('Reset positions'));
  expect(screen.getByTestId('hud').style.left).toBe('14px');
});
