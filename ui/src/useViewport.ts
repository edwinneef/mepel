import { useCallback, useEffect, useRef, useState } from 'react';
import type { FrozenFrame, Rect, Selection, Snapshot } from './contracts';
import { EngineClient } from './client';

export interface ViewImage {
  url: string; width: number; height: number; key: string; capturedAt?: number; sourceId?: string;
  observation?: Snapshot;
}

export function useViewport(client: EngineClient, snapshot: Snapshot | null, connected: boolean, analyzed = false) {
  const [image, setImage] = useState<ViewImage | null>(null);
  const [frozen, setFrozen] = useState<FrozenFrame | null>(null);
  const [selection, setSelection] = useState<Rect | null>(null);
  const [freezing, setFreezing] = useState(false);
  const version = useRef(0);
  const frozenRef = useRef<FrozenFrame | null>(null);
  const freezingRef = useRef(false);
  const sessionRef = useRef<string | null>(null);
  const sourceRef = useRef<string | null>(null);
  const requested = useRef<string | null>(null);
  const pending = useRef<string | null>(null);
  const liveRequest = useRef<AbortController | null>(null);
  const analyzedRef = useRef(analyzed);

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
    if (snapshot && (sessionRef.current !== snapshot.session_id || sourceRef.current !== snapshot.frame.source_id)) {
      sessionRef.current = snapshot.session_id;
      sourceRef.current = snapshot.frame.source_id;
      clear();
    }
  }, [snapshot?.session_id, snapshot?.frame.source_id, clear]);

  useEffect(() => {
    if (analyzedRef.current !== analyzed) {
      version.current += 1; liveRequest.current?.abort();
      requested.current = null; pending.current = null;
      analyzedRef.current = analyzed;
    }
    const frame = analyzed ? snapshot?.frame : snapshot?.preview_frame ?? snapshot?.frame;
    if (!connected || frozenRef.current || freezingRef.current) return;
    if (!frame?.available || !frame.id) {
      version.current += 1; requested.current = null; pending.current = null;
      liveRequest.current?.abort();
      // A discarded capture does not change the source. Keep its last good image
      // and dimensions until a valid replacement arrives; the UI labels it stale.
      return;
    }
    if (requested.current === frame.id) return;
    if (pending.current) return;
    requested.current = frame.id;
    pending.current = frame.id;
    const current = ++version.current;
    liveRequest.current?.abort();
    const controller = new AbortController();
    liveRequest.current = controller;
    const frameId = frame.id;
    void (async () => {
      let replacement: string | null = null;
      try {
        const endpoint = !analyzed && snapshot?.preview_frame ? 'preview' : 'frame';
        const response = await fetch(`/api/v1/${endpoint}?id=${encodeURIComponent(frameId)}`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(3000)]), cache: 'no-store',
        });
        if (response.status === 409) { if (current === version.current) requested.current = null; return; }
        if (!response.ok) throw new Error('Game frame unavailable');
        const blob = await response.blob();
        if (current !== version.current || frozenRef.current || freezingRef.current) return;
        replacement = URL.createObjectURL(blob);
        const decoded = new Image();
        const loaded = new Promise<void>((resolve, reject) => {
          decoded.onload = () => resolve();
          decoded.onerror = () => reject(new Error('Could not load game frame'));
        });
        decoded.src = replacement;
        // Hidden browser tabs can defer decode() until painting resumes.
        await (typeof decoded.decode === 'function' ? Promise.race([decoded.decode(), loaded]) : loaded);
        if (current !== version.current || frozenRef.current || freezingRef.current) return;
        setImage({ url: replacement, width: frame.width, height: frame.height, key: frameId,
          capturedAt: frame.captured_at ?? 0, sourceId: frame.source_id,
          observation: analyzed ? snapshot ?? undefined : undefined });
        replacement = null;
      } catch (error) {
        if (current === version.current) { requested.current = null; client.fail(error); }
      } finally {
        if (replacement) URL.revokeObjectURL(replacement);
        if (current === version.current && pending.current === frameId) pending.current = null;
      }
    })();
  }, [snapshot, connected, frozen, freezing, client, analyzed]);

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
