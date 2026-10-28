import { useEffect, useState } from 'react';
import type { LiveDetections } from './contracts';

// A separate, bounded read path. These packets never replace the command snapshot.
export function useDrawings(connected: boolean, session: string | undefined) {
  const [value, setValue] = useState<{ session?: string; drawing: LiveDetections | null } | null>(null);
  useEffect(() => {
    if (!connected || !session) return;
    let closed = false, supported = false;
    let timer: ReturnType<typeof setTimeout>;
    let expiry: ReturnType<typeof setTimeout>;
    let controller: AbortController | null = null;
    let latest: LiveDetections | null = null;
    const poll = async () => {
      const began = performance.now();
      controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 400);
      try {
        const response = await fetch('/api/v1/drawings', { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error(`Drawings ${response.status}`);
        let drawing = await response.json() as LiveDetections | null;
        if (drawing !== null && (!drawing.frame || typeof drawing.frame.source_id !== 'string')) {
          throw new Error('Invalid drawing packet');
        }
        if (closed) return;
        supported = true;
        const age = drawing?.frame.captured_at == null ? Infinity : Date.now() - drawing.frame.captured_at * 1000;
        if (drawing && (!drawing.frame.available || age < -50 || age >= 500)) drawing = null;
        // A late packet from a prior engine must not cross the session boundary.
        if (drawing && !drawing.frame.source_id.startsWith(`${session}:`)) {
          latest = null;
          setValue({ session, drawing: null });
        } else if (drawing === null || drawing.frame.id !== latest?.frame.id
          || drawing.frame.source_id !== latest?.frame.source_id) {
          latest = drawing;
          setValue({ session, drawing });
          clearTimeout(expiry);
          if (drawing) expiry = setTimeout(() => { latest = null; setValue({ session, drawing: null }); }, Math.max(0, 500 - age));
        }
      } catch {
        // Once supported, a transport failure clears drawings instead of reviving
        // the older recognition snapshot. Older engines retain their fallback.
        if (!closed && supported) { latest = null; setValue({ session, drawing: null }); }
      } finally {
        clearTimeout(timeout);
        if (!closed) timer = setTimeout(poll, supported ? Math.max(0, 1000 / 30 - (performance.now() - began)) : 1000);
      }
    };
    void poll();
    return () => { closed = true; clearTimeout(timer); clearTimeout(expiry); controller?.abort(); };
  }, [connected, session]);
  return connected && value && value.session === session ? value.drawing : undefined;
}
