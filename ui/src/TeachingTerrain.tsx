import { useEffect, useRef, useState } from 'react';
import type { AreaSegment, AreaView, TaughtGeometry } from './contracts';

export function shortId(id: string): string {
  return id.replace(/^walk_([pr])(\d+)$/, (_, kind: string, n: string) => `${kind.toUpperCase()}${n}`);
}

export function placeName(item?: AreaSegment): string {
  return item?.name ?? (item ? `Platform ${shortId(item.id)}` : 'Starting floor');
}

interface Props {
  geometry: TaughtGeometry; references: AreaView[]; selected?: AreaSegment; target?: AreaSegment;
}

export function TeachingTerrain({ geometry, references, selected, target }: Props) {
  const visible = (view: AreaView, item?: AreaSegment) => item &&
    Math.max(item.start.x, item.end.x) >= view.origin.x &&
    Math.min(item.start.x, item.end.x) <= view.origin.x + view.width / view.scale &&
    Math.max(item.start.y, item.end.y) >= view.origin.y &&
    Math.min(item.start.y, item.end.y) <= view.origin.y + view.height / view.scale;
  const view = references.find(candidate => visible(candidate, selected));
  const image = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const element = image.current;
    if (!element) return;
    const measure = () => {
      const { width, height } = element.getBoundingClientRect();
      setSize({ width, height });
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(element);
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [view?.image, selected?.id]);
  if (!view || !selected) return <div className="reference-unavailable"><p>No saved picture covers this place.</p>
    <p>Its learned coordinates remain in the map. A matching reference can be added from Advanced.</p>
    <svg className="terrain-fallback" viewBox={`${geometry.boundary?.x ?? 0} ${geometry.boundary?.y ?? 0} ${geometry.boundary?.width ?? 1} ${geometry.boundary?.height ?? 1}`} role="img" aria-label="Learned map">
      {[...geometry.platforms, ...geometry.ropes].map(p => <line key={p.id} x1={p.start.x} y1={p.start.y} x2={p.end.x} y2={p.end.y} className={p.id === selected?.id ? 'terrain-source' : 'terrain-other'} />)}
    </svg></div>;
  const point = (p: { x: number; y: number }) => ({ x: (p.x - view.origin.x) * view.scale, y: (p.y - view.origin.y) * view.scale });
  const a = point(selected.start), b = point(selected.end);
  const middle = (a.x + b.x) / 2;
  const other = target && visible(view, target) && target.id !== selected.id ? target : undefined;
  const floor = other ? point({ x: (selected.start.x + selected.end.x) / 2, y: other.start.y }) : b;
  const width = Math.min(view.width, Math.max(460, Math.abs(a.x - b.x) + 110));
  const height = Math.min(view.height, Math.max(330, Math.max(a.y, b.y, floor.y) - Math.min(a.y, b.y, floor.y) + 130));
  const left = Math.max(0, Math.min(view.width - width, middle - width / 2));
  const top = Math.max(0, Math.min(view.height - height, Math.min(a.y, b.y, floor.y) - 85));
  const shapes = [selected, ...(other ? [other] : [])];
  const partial = shapes.some(item => [item.start, item.end].some(p => {
    const q = point(p); return q.x < 0 || q.x > view.width || q.y < 0 || q.y > view.height;
  }));
  const scale = size.width && size.height ? Math.min(size.width / width, size.height / height) : 1;
  const font = 14 / scale;
  const padding = 10 / scale, labelHeight = 32 / scale;
  return <section className="teaching-terrain" aria-label="Places in the saved game picture">
    <div className="terrain-heading"><strong>{placeName(selected)}</strong><span>Saved reference{partial ? ' · partial coverage' : ''}</span></div>
    <svg ref={image} className="terrain-image" viewBox={`${left} ${top} ${width} ${height}`} role="img" aria-label={`${placeName(selected)}${other ? ` and ${placeName(other)}` : ''} on actual terrain`}>
      <image href={`/api/v1/area-frame?id=${encodeURIComponent(view.image)}`} width={view.width} height={view.height} />
      {shapes.map((item, index) => {
        const start = point(item.start), end = point(item.end);
        const text = `${placeName(item)} · ${shortId(item.id)}`;
        const boxWidth = Math.min(width - 2 * padding, text.length * font * .6 + 2 * padding);
        const x = Math.max(left + padding, Math.min(left + width - boxWidth - padding, (start.x + end.x) / 2 + 20));
        const y = Math.max(top + padding, Math.min(top + height - labelHeight - padding, start.y - 56 / scale));
        const leader = `M${Math.max(left + padding, Math.min(left + width - padding, (start.x + end.x) / 2))} ${start.y} L${x + padding} ${y + labelHeight}`;
        return <g key={item.id} className={index ? 'terrain-destination' : 'terrain-source'}>
          <line className="terrain-outline" x1={start.x} y1={start.y} x2={end.x} y2={end.y} />
          <line x1={start.x} y1={start.y} x2={end.x} y2={end.y} />
          <path className="terrain-outline" d={leader} />
          <path d={leader} />
          <rect x={x} y={y} width={boxWidth} height={labelHeight} rx={5 / scale} vectorEffect="non-scaling-stroke" />
          <text x={x + padding} y={y + 21 / scale} fontSize={font}>{text}</text>
        </g>;
      })}
    </svg>
    <p className="terrain-caption">Saved picture · highlighted places are learned estimates.</p>
  </section>;
}
