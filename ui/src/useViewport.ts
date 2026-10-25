import { useCallback, useEffect, useRef, useState } from 'react';
import type { FrozenFrame, Rect, Selection, Snapshot } from './contracts';
import { EngineClient } from './client';

export interface ViewImage { url: string; width: number; height: number; key: string }

export function useViewport(client: EngineClient, snapshot: Snapshot | null, connected: boolean) {
  const [image, setImage] = useState<ViewImage | null>(null);
  const [frozen, setFrozen] = useState<FrozenFrame | null>(null);
  const [selection, setSelection] = useState<Rect | null>(null);
  const [freezing, setFreezing] = useState(false);
  const version = useRef(0);
  const frozenRef = useRef<FrozenFrame | null>(null);
  const freezingRef = useRef(false);
  const sessionRef = useRef<string | null>(null);
  const requested = useRef<string | null>(null);
  const pending = useRef<string | null>(null);
  const liveRequest = useRef<AbortController | null>(null);

  useEffect(() => () => { if (image) URL.revokeObjectURL(image.url); }, [image]);
  useEffect(() => () => { version.current += 1; liveRequest.current?.abort(); }, []);

  const clear = useCallback(() => {
    version.current += 1;
    liveRequest.current?.abort();
    frozenRef.current = null;
    freezingRef.current = false;
    requested.current = null;
    pending.current = null;
    setImage(null); setFrozen(null); setSelection(null); setFreezing(false);
  }, []);

  useEffect(() => {
    if (snapshot && sessionRef.current !== snapshot.session_id) {
      sessionRef.current = snapshot.session_id;
      clear();
    }
  }, [snapshot?.session_id, clear]);

  useEffect(() => {
    const frame = snapshot?.frame;
    if (!connected || frozenRef.current || freezingRef.current) return;
    if (!frame?.available || !frame.id) {
      version.current += 1; requested.current = null; pending.current = null;
      setImage(previous => previous === null ? previous : null);
      return;
    }
    if (requested.current === frame.id) return;
    if (pending.current === frame.id) return;
    requested.current = frame.id;
    pending.current = frame.id;
    const current = ++version.current;
    liveRequest.current?.abort();
    const controller = new AbortController();
    liveRequest.current = controller;
    const frameId = frame.id;
    void (async () => {
      try {
        const response = await fetch(`/api/v1/frame?id=${encodeURIComponent(frameId)}`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(3000)]), cache: 'no-store',
        });
        if (response.status === 409) { if (current === version.current) requested.current = null; return; }
        if (!response.ok) throw new Error('Game frame unavailable');
        const blob = await response.blob();
        if (current !== version.current || frozenRef.current || freezingRef.current) return;
        setImage({ url: URL.createObjectURL(blob), width: frame.width, height: frame.height, key: frameId });
      } catch (error) {
        if (current === version.current) { requested.current = null; client.fail(error); }
      } finally {
        if (pending.current === frameId) pending.current = null;
      }
    })();
  }, [snapshot, connected, frozen, freezing, client]);

  const freeze = async () => {
    const current = ++version.current;
    liveRequest.current?.abort();
    freezingRef.current = true; setFreezing(true);
    try {
      const frame = await client.command<FrozenFrame>('freeze');
      if (current !== version.current) return;
      const response = await fetch(`/frame.png?id=${encodeURIComponent(frame.id)}`, { signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error('Frozen frame expired; freeze a new screenshot');
      const blob = await response.blob();
      if (current !== version.current) return;
      frozenRef.current = frame; setFrozen(frame); setSelection(null);
      setImage({ url: URL.createObjectURL(blob), width: frame.width, height: frame.height, key: frame.id });
      client.message('Frozen. Drag a rectangle over the game view.');
    } finally {
      if (current === version.current) { freezingRef.current = false; setFreezing(false); }
    }
  };

  const live = async () => {
    version.current += 1;
    if (freezingRef.current) await client.command('pause');
    await client.command('resume_view');
    clear();
    client.message('Returned to live view.');
  };

  const selected = (): Selection => {
    if (!frozenRef.current || !selection || selection.width < 2 || selection.height < 2) {
      throw new Error('Freeze the view and select a rectangle first');
    }
    return { id: frozenRef.current.id, ...selection };
  };

  return { image, frozen, selection, freezing, freeze, live, clear, selected, setSelection };
}
