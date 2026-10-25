import { useEffect, useRef, useState } from 'react';
import { EngineClient } from './client';
import type { AreaPoint, AreaProfile, AreaView } from './contracts';
import { drawArea, newArea, removeAreaItem } from './area';
import type { DrawTool } from './area';

interface SavedArea { id: string; name: string; revision: number }
type OpenRequest = { kind: 'new' } | { kind: 'load'; id: string };

export function useAreaEditor(client: EngineClient, sessionId?: string, serverEditing?: boolean, serverEpoch?: number) {
  const [draft, setDraft] = useState<AreaProfile | null>(null);
  const draftRef = useRef<AreaProfile | null>(null);
  const [editing, setEditing] = useState(false);
  const editingRef = useRef(false);
  const [dirty, setDirty] = useState(false);
  const [working, setWorking] = useState(false);
  const workingRef = useRef(false);
  const [areas, setAreas] = useState<SavedArea[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [activeViewId, setActiveViewId] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tool, setTool] = useState<DrawTool>('select');
  const [pendingOpen, setPendingOpen] = useState<OpenRequest | null>(null);
  const lastSession = useRef(sessionId);
  const grantedEpoch = useRef<number | null>(null);
  const serverBacked = useRef(false);
  serverBacked.current = typeof serverEditing === 'boolean' && typeof serverEpoch === 'number';

  useEffect(() => {
    if (lastSession.current !== sessionId) {
      lastSession.current = sessionId;
      grantedEpoch.current = null;
      editingRef.current = false; setEditing(false); setSelectedId(null);
    }
  }, [sessionId]);

  useEffect(() => {
    // Ignore status captured before Begin completed. A later engine revocation
    // removes mutation permission without discarding the operator's draft.
    if (serverEditing === false && serverEpoch !== undefined && grantedEpoch.current !== null
      && serverEpoch >= grantedEpoch.current && editingRef.current) {
      grantedEpoch.current = null; editingRef.current = false; setEditing(false);
      client.message('Area editing ended in the engine. Draft retained; begin editing to make changes.');
    }
  }, [serverEditing, serverEpoch, client]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const replaceDraft = (profile: AreaProfile, changed: boolean) => {
    draftRef.current = profile; setDraft(profile); setDirty(changed);
  };
  const requireEditing = () => {
    if (!editingRef.current) throw new Error('Begin area editing first. Gameplay input must be stopped.');
  };
  const fail = (value: unknown) => {
    const message = value instanceof Error ? value.message : String(value);
    setError(message); client.fail(value);
  };
  const perform = async (operation: () => Promise<void>) => {
    if (workingRef.current) { fail(new Error('Wait for the area operation to finish.')); return; }
    workingRef.current = true; setWorking(true); setError('');
    try { await operation(); } catch (value) { fail(value); }
    finally { workingRef.current = false; setWorking(false); }
  };
  const begin = async () => {
    const result = await client.command<{ editing: boolean }>('area_begin');
    if (!result.editing) throw new Error('The engine did not enter stopped area editing.');
    if (serverBacked.current) {
      const confirmed = await client.readStatus();
      if (!confirmed.area_editing) {
        grantedEpoch.current = null; editingRef.current = false; setEditing(false);
        throw new Error('Area editing ended before confirmation. Begin editing again.');
      }
      grantedEpoch.current = confirmed.command_epoch;
    }
    editingRef.current = true; setEditing(true);
  };
  const mutate = (change: (profile: AreaProfile) => AreaProfile) => {
    try {
      requireEditing();
      if (workingRef.current) throw new Error('Wait for the area operation to finish.');
      if (!draftRef.current) throw new Error('Create or load an area first.');
      replaceDraft(change(draftRef.current), true); setError('');
    } catch (value) { fail(value); }
  };
  const refresh = () => perform(async () => {
    const result = await client.command<{ areas: SavedArea[]; errors: string[] }>('area_list');
    setAreas(result.areas); setWarnings(result.errors);
  });
  const open = (request: OpenRequest, discard = false) => {
    if (dirty && !discard) { setPendingOpen(request); return Promise.resolve(); }
    return perform(async () => {
      await begin();
      if (request.kind === 'new') { replaceDraft(newArea(), true); setWarnings([]); setActiveViewId(''); }
      else {
        const result = await client.command<{ profile: AreaProfile; warnings: string[] }>('area_load', { area_id: request.id });
        replaceDraft(result.profile, false); setWarnings(result.warnings); setActiveViewId(result.profile.views[0]?.id ?? '');
      }
      setPendingOpen(null); setSelectedId(null); setTool('select');
      client.message('Area editing. Gameplay input is stopped.');
    });
  };
  const capture = () => perform(async () => {
    requireEditing();
    if (!draftRef.current) throw new Error('Create or load an area first.');
    const result = await client.command<{ view: AreaView }>('area_capture');
    requireEditing();
    const previous = draftRef.current;
    replaceDraft({ ...previous, views: [...previous.views, result.view], boundary: previous.views.length ? previous.boundary
      : { x: 0, y: 0, width: result.view.width, height: result.view.height } }, true);
    setActiveViewId(result.view.id); setSelectedId(null);
    client.message('Reference captured. Draw on this fixed image; align additional views manually.');
  });
  const save = () => perform(async () => {
    requireEditing();
    if (!draftRef.current) throw new Error('Create or load an area first.');
    const result = await client.command<{ profile: AreaProfile; warnings: string[] }>('area_save', { profile: draftRef.current });
    replaceDraft(result.profile, false); setWarnings(result.warnings);
    setAreas(previous => [...previous.filter(item => item.id !== result.profile.id), {
      id: result.profile.id, name: result.profile.name, revision: result.profile.revision,
    }]);
    client.message(`Saved ${result.profile.name}. Editing remains stopped; navigation is not enabled.`);
  });
  const end = () => perform(async () => {
    await client.command('area_end'); grantedEpoch.current = null; editingRef.current = false; setEditing(false);
    client.message(dirty ? 'Editing ended. Unsaved draft retained; gameplay remains stopped.' : 'Editing ended. Gameplay remains stopped.');
  });
  const draw = (from: AreaPoint, to: AreaPoint) => {
    if (tool === 'select') return;
    mutate(profile => {
      const view = profile.views.find(item => item.id === activeViewId);
      if (!view) throw new Error('Capture or select a reference view first.');
      const result = drawArea(profile, view, tool, from, to);
      setSelectedId(result.selected); return result.profile;
    });
  };
  const removeSelected = () => {
    if (!selectedId || selectedId === 'boundary') return;
    mutate(profile => removeAreaItem(profile, selectedId)); setSelectedId(null);
  };

  return {
    draft, editing, dirty, working, areas, warnings, error, activeViewId, selectedId, tool, pendingOpen,
    view: draft?.views.find(item => item.id === activeViewId) ?? null,
    refresh, create: () => open({ kind: 'new' }), load: (id: string) => open({ kind: 'load', id }),
    confirmDiscard: () => pendingOpen ? open(pendingOpen, true) : Promise.resolve(), cancelDiscard: () => setPendingOpen(null),
    resume: () => perform(begin), capture, save, end, mutate, draw, removeSelected,
    setActiveViewId, setSelectedId, setTool,
  };
}

export type AreaWorkspace = ReturnType<typeof useAreaEditor>;
