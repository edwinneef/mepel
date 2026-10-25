import { useEffect, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import type { AreaPoint, AreaProfile, AreaView, AreaLink } from './contracts';
import { areaErrors, graphWarnings, hitArea, midpoint, newElementId, toArea, toView } from './area';
import { nativePoint, rectangle } from './selection';
import type { AreaWorkspace } from './useAreaEditor';

const toolNames = { select: 'Select', boundary: 'Hunt boundary', avoid: 'Avoid zone', portal: 'Portal zone', platform: 'Platform', rope: 'Rope / ladder' } as const;

export function AreaCanvas({ workspace, disabled }: { workspace: AreaWorkspace; disabled: boolean }) {
  const { draft, view, tool, selectedId } = workspace;
  const imageRef = useRef<HTMLImageElement>(null);
  const [loaded, setLoaded] = useState('');
  const [drag, setDrag] = useState<{ start: AreaPoint; end: AreaPoint } | null>(null);
  useEffect(() => { setDrag(null); }, [view?.id, tool]);
  if (!draft || !view) return <div className="viewport"><div className="empty-view"><h2>Capture a reference view</h2>
    <p>Use Navigation to capture this part of your hunting area.<br />Gameplay input is stopped while editing.</p></div></div>;
  const ready = loaded === view.image && workspace.editing && !disabled;
  const point = (event: PointerEvent): AreaPoint => nativePoint({ x: event.clientX, y: event.clientY },
    imageRef.current!.getBoundingClientRect(), view.width, view.height);
  const begin = (event: PointerEvent<HTMLDivElement>) => {
    if (!ready || !imageRef.current) return;
    const start = point(event);
    if (tool === 'select') { workspace.setSelectedId(hitArea(draft, toArea(start, view), 8 / view.scale)); return; }
    event.currentTarget.setPointerCapture(event.pointerId); setDrag({ start, end: start });
  };
  const finish = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag || !ready) return;
    workspace.draw(drag.start, point(event)); setDrag(null);
  };
  const rect = (value: AreaProfile['boundary']) => {
    const origin = toView(value, view);
    return { x: origin.x, y: origin.y, width: value.width * view.scale, height: value.height * view.scale };
  };
  const segment = (item: AreaProfile['platforms'][number]) => {
    const start = toView(item.start, view), end = toView(item.end, view);
    return { x1: start.x, y1: start.y, x2: end.x, y2: end.y };
  };
  const nodes = [...draft.platforms, ...draft.ropes];
  return <div className="viewport area-viewport" aria-label="Hunting area reference">
    <div className={`image-surface area-surface ${tool === 'select' ? '' : 'drawing'}`} style={{ aspectRatio: `${view.width} / ${view.height}` }}
      onPointerDown={begin} onPointerMove={event => { if (drag && ready) setDrag({ ...drag, end: point(event) }); }}
      onPointerUp={finish} onPointerCancel={() => setDrag(null)}>
      <img key={view.image} ref={imageRef} src={`/api/v1/area-frame?id=${encodeURIComponent(view.image)}`} alt={`Area reference: ${view.name}`}
        width={view.width} height={view.height} draggable={false} onLoad={() => setLoaded(view.image)} onError={() => setLoaded('')} />
      <svg className="selection-layer area-overlay" viewBox={`0 0 ${view.width} ${view.height}`} aria-hidden="true" preserveAspectRatio="none">
        <rect {...rect(draft.boundary)} className={`area-boundary ${selectedId === 'boundary' ? 'chosen' : ''}`} />
        {draft.zones.map(zone => <g key={zone.id}><rect {...rect(zone.rect)} className={`area-zone ${zone.kind} ${selectedId === zone.id ? 'chosen' : ''}`} />
          <text x={rect(zone.rect).x + 4} y={rect(zone.rect).y + 15}>{zone.kind.toUpperCase()}</text></g>)}
        {draft.links.map(link => {
          const from = nodes.find(node => node.id === link.from), to = nodes.find(node => node.id === link.to);
          if (!from || !to) return null;
          const a = toView(midpoint(from), view), b = toView(midpoint(to), view);
          return <g key={link.id} className={`area-link ${selectedId === link.id ? 'chosen' : ''}`}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} /><circle cx={b.x} cy={b.y} r="4" />
          </g>;
        })}
        {draft.platforms.map((item, index) => <g key={item.id} className={`area-platform ${selectedId === item.id ? 'chosen' : ''}`}>
          <line {...segment(item)} /><text x={toView(item.start, view).x + 4} y={toView(item.start, view).y - 7}>P{index + 1}</text></g>)}
        {draft.ropes.map((item, index) => <g key={item.id} className={`area-rope ${selectedId === item.id ? 'chosen' : ''}`}>
          <line {...segment(item)} /><text x={toView(item.start, view).x + 6} y={toView(item.start, view).y + 15}>R{index + 1}</text></g>)}
        {drag && (tool === 'platform' || tool === 'rope' ? <line className="area-draft" x1={drag.start.x} y1={drag.start.y}
          x2={tool === 'rope' ? drag.start.x : drag.end.x} y2={drag.end.y} /> : <rect className="area-draft" {...rectangle(drag.start, drag.end)} />)}
      </svg>
      {loaded !== view.image && <span className="area-loading">Loading fixed reference…</span>}
    </div>
  </div>;
}

interface EditorProps { workspace: AreaWorkspace; active: boolean; connected: boolean; disabled: boolean }

export function AreaEditor({ workspace: w, active, connected, disabled }: EditorProps) {
  const [chosenArea, setChosenArea] = useState('');
  const [alignment, setAlignment] = useState({ x: '0', y: '0', scale: '1' });
  const [boundary, setBoundary] = useState({ x: '0', y: '0', width: '1', height: '1' });
  const [link, setLink] = useState<{ from: string; to: string; kind: AreaLink['kind'] }>({ from: '', to: '', kind: 'walk' });
  const draft = w.draft, view = w.view;
  const busy = disabled || w.working;
  const locked = busy || !w.editing;
  useEffect(() => { if (active && connected) void w.refresh(); }, [active, connected]);
  useEffect(() => { if (view) setAlignment({ x: String(view.origin.x), y: String(view.origin.y), scale: String(view.scale) }); }, [view?.id, view?.origin.x, view?.origin.y, view?.scale]);
  useEffect(() => { if (draft) setBoundary({ x: String(draft.boundary.x), y: String(draft.boundary.y), width: String(draft.boundary.width), height: String(draft.boundary.height) }); }, [draft?.boundary]);
  const errors = draft ? areaErrors(draft) : [];
  const warnings = [...new Set([...w.warnings, ...(draft ? graphWarnings(draft) : [])])];
  const nodes = draft ? [...draft.platforms, ...draft.ropes] : [];
  const items = draft ? [
    { id: 'boundary', label: 'Hunting boundary' },
    ...draft.platforms.map((item, i) => ({ id: item.id, label: `Platform ${i + 1}` })),
    ...draft.ropes.map((item, i) => ({ id: item.id, label: `Rope ${i + 1}` })),
    ...draft.zones.map((item, i) => ({ id: item.id, label: `${item.kind} zone ${i + 1}` })),
    ...draft.links.map((item, i) => ({ id: item.id, label: `Link ${i + 1}: ${item.kind}` })),
  ] : [];
  const align = () => w.mutate(profile => {
    const x = Number(alignment.x), y = Number(alignment.y), scale = Number(alignment.scale);
    if (![x, y, scale].every(Number.isFinite) || scale <= 0) throw new Error('Alignment needs finite coordinates and a positive scale.');
    return { ...profile, views: profile.views.map(item => item.id === w.activeViewId ? { ...item, origin: { x, y }, scale } : item) };
  });
  const addLink = () => w.mutate(profile => {
    if (!nodes.some(item => item.id === link.from) || !nodes.some(item => item.id === link.to) || link.from === link.to) throw new Error('Choose two different taught surfaces for the link.');
    if (profile.links.some(item => item.from === link.from && item.to === link.to)) throw new Error('That directed link already exists.');
    const item = { id: newElementId('link'), ...link }; w.setSelectedId(item.id);
    return { ...profile, links: [...profile.links, item] };
  });

  return <><p className="tool-intro">Teach one hunting area on fixed reference images. Editing releases gameplay input. Movement remains unavailable.</p>
    <section className="tool-group"><h3>Saved areas</h3><label>Hunting area<select value={chosenArea} onChange={event => setChosenArea(event.target.value)}>
      <option value="">Choose an area…</option>{w.areas.map(area => <option key={area.id} value={area.id}>{area.name} · revision {area.revision}</option>)}</select></label>
      <div className="button-grid"><button disabled={busy} onClick={() => void w.create()}>New area</button><button disabled={busy || !chosenArea} onClick={() => void w.load(chosenArea)}>Load area</button>
        <button disabled={busy} onClick={() => void w.refresh()}>Refresh areas</button></div>
      {w.pendingOpen && <div className="area-alert"><p>This draft has unsaved changes.</p><button disabled={busy} onClick={() => void w.confirmDiscard()}>Discard draft and continue</button><button onClick={w.cancelDiscard}>Keep draft</button></div>}
    </section>
    {draft && <><section className="tool-group"><h3>{w.dirty ? 'Unsaved draft' : `Saved · revision ${draft.revision}`}</h3>
      <label>Area name<input disabled={locked} value={draft.name} onChange={event => w.mutate(profile => ({ ...profile, name: event.target.value }))} /></label>
      <div className="button-grid">{w.editing ? <button disabled={busy} onClick={() => void w.end()}>Exit editing</button> : <button disabled={busy} onClick={() => void w.resume()}>Begin editing · stop input</button>}
        <button disabled={locked || !w.dirty || Boolean(errors.length)} onClick={() => void w.save()}>Save area</button></div>
      <p>{w.editing ? 'Editing · input stopped' : 'Draft retained. Begin editing to change it.'}</p>
    </section><section className="tool-group"><h3>Reference views</h3>
      <label>Reference view<select disabled={locked} value={w.activeViewId} onChange={event => w.setActiveViewId(event.target.value)}>
        <option value="">No reference selected</option>{draft.views.map(item => <option key={item.id} value={item.id}>{item.name} · {item.width}×{item.height}</option>)}</select></label>
      <div className="button-grid"><button disabled={locked} onClick={() => void w.capture()}>Capture reference view</button>
        <button disabled={locked || !view} onClick={() => { w.mutate(profile => ({ ...profile, views: profile.views.filter(item => item.id !== w.activeViewId) })); w.setActiveViewId(draft.views.find(item => item.id !== w.activeViewId)?.id ?? ''); }}>Remove view</button></div>
      {view && <label>View name<input disabled={locked} value={view.name} onChange={event => w.mutate(profile => ({ ...profile, views: profile.views.map(item => item.id === view.id ? { ...item, name: event.target.value } : item) }))} /></label>}
      {view && <details><summary>Align this view manually</summary><p>Origin is the area coordinate at this image's top-left. Match shared landmarks before drawing. Scale maps area units to image pixels.</p>
        <div className="field-grid"><label>View origin X<input disabled={locked} type="number" value={alignment.x} onChange={event => setAlignment({ ...alignment, x: event.target.value })} /></label>
          <label>View origin Y<input disabled={locked} type="number" value={alignment.y} onChange={event => setAlignment({ ...alignment, y: event.target.value })} /></label></div>
        <label>View scale<input disabled={locked} type="number" min="0.001" step="0.01" value={alignment.scale} onChange={event => setAlignment({ ...alignment, scale: event.target.value })} /></label>
        <button disabled={locked} onClick={align}>Apply view alignment</button></details>}
    </section><section className="tool-group"><h3>Draw on the reference</h3><div className="area-tools">{(Object.keys(toolNames) as Array<keyof typeof toolNames>).map(tool =>
      <button key={tool} disabled={locked || !view} aria-pressed={w.tool === tool} onClick={() => w.setTool(tool)}>{toolNames[tool]}</button>)}</div>
      <p>Drag to draw. Ropes stay vertical. Select a shape or choose it below to remove it.</p>
      <label>Selected item<select disabled={locked} value={w.selectedId ?? ''} onChange={event => w.setSelectedId(event.target.value || null)}><option value="">None</option>
        {items.map(item => <option key={item.id} value={item.id}>{item.label} · {item.id}</option>)}</select></label>
      <button disabled={locked || !w.selectedId || w.selectedId === 'boundary'} onClick={w.removeSelected}>Remove selected item</button>
      <p>Removing a surface also removes its connected links.</p>
      <details><summary>Hunting boundary dimensions</summary><div className="field-grid">{(['x', 'y', 'width', 'height'] as const).map(key =>
        <label key={key}>Boundary {key}<input disabled={locked} type="number" value={boundary[key]} onChange={event => setBoundary({ ...boundary, [key]: event.target.value })} /></label>)}</div>
        <button disabled={locked} onClick={() => w.mutate(profile => {
          const value = { x: Number(boundary.x), y: Number(boundary.y), width: Number(boundary.width), height: Number(boundary.height) };
          if (!Object.values(value).every(Number.isFinite) || value.width <= 0 || value.height <= 0) throw new Error('Use finite coordinates and positive boundary dimensions.');
          return { ...profile, boundary: value };
        })}>Apply boundary dimensions</button></details>
    </section><section className="tool-group"><h3>Directed movement links</h3><p>A link describes a taught connection. It does not test or execute a move.</p>
      {(['from', 'to'] as const).map(key => <label key={key}>Link {key}<select disabled={locked} value={link[key]} onChange={event => setLink({ ...link, [key]: event.target.value })}>
        <option value="">Choose a surface…</option>{nodes.map(item => <option key={item.id} value={item.id}>{items.find(entry => entry.id === item.id)?.label} · {item.id}</option>)}</select></label>)}
      <label>Link kind<select disabled={locked} value={link.kind} onChange={event => setLink({ ...link, kind: event.target.value as AreaLink['kind'] })}>{(['walk', 'jump', 'climb', 'drop'] as const).map(kind => <option key={kind} value={kind}>{kind}</option>)}</select></label>
      <button disabled={locked || !link.from || !link.to} onClick={addLink}>Add directed link</button>
    </section></>}
    {(w.error || errors.length > 0 || warnings.length > 0) && <section className="tool-group area-checks"><h3>Area checks</h3>
      {w.error && <p className="area-error" role="alert">{w.error}</p>}{errors.length > 0 && <ul className="area-error">{errors.map(message => <li key={message}>{message}</li>)}</ul>}
      {warnings.length > 0 && <><span className="eyebrow">Warnings</span><ul>{warnings.map(message => <li key={message}>{message}</li>)}</ul><p>Graph reachability is not proof that a jump or climb is physically possible.</p></>}
    </section>}
  </>;
}
