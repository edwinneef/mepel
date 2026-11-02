import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PlayerCapture } from './PlayerCapture';
import { EngineClient } from './client';
import { snapshot } from './test-fixtures';
afterEach(cleanup);
it('starts a shared bounded collection without a rectangle and supports cancellation', async () => {
  const client = new EngineClient('token', vi.fn());
  const command = vi.spyOn(client, 'command').mockResolvedValue({});
  const poses = { enabled: false, identity: '', outfit: '', identities: ['name'], saved: 0, duplicates: 0, rejected: 0, pending: 0, limit: 32, reason: 'Off' };
  const props = { snapshot: snapshot({ pose_collection: poses }), client, act: async (op: () => Promise<unknown>) => { await op(); }, disabled: false };
  const view = render(<PlayerCapture {...props} />);
  fireEvent.click(screen.getByText('Capture player screenshots'));
  await waitFor(() => expect(command).toHaveBeenCalledWith('pose_collection', expect.objectContaining({ enabled: true, identity: 'name' })));
  view.rerender(<PlayerCapture {...props} snapshot={snapshot({ pose_collection: { ...poses, enabled: true } })} />);
  fireEvent.click(screen.getByText('Cancel screenshot capture'));
  await waitFor(() => expect(command).toHaveBeenCalledWith('pose_collection', { enabled: false }));
});
it('requires a taught identity', () => {
  render(<PlayerCapture snapshot={snapshot()} client={new EngineClient('token', vi.fn())} act={async op => { await op(); }} disabled={false} />);
  expect((screen.getByText('Capture player screenshots') as HTMLButtonElement).disabled).toBe(true);
});
