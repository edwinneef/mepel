import { useRef } from 'react';
import type { PointerEvent, ReactNode } from 'react';
import type { Rect } from './contracts';
import type { ViewImage } from './useViewport';
import { nativePoint, rectangle } from './selection';
import type { Point } from './selection';

interface Props {
  image: ViewImage | null;
  frozen: boolean;
  stale?: boolean;
  selection: Rect | null;
  onSelection: (selection: Rect) => void;
  overlay?: ReactNode;
}

export function GameViewport({ image, frozen, stale = false, selection, onSelection, overlay }: Props) {
  const imageRef = useRef<HTMLImageElement>(null);
  const origin = useRef<Point | null>(null);
  const point = (event: PointerEvent): Point => nativePoint(
    { x: event.clientX, y: event.clientY }, imageRef.current!.getBoundingClientRect(),
    image!.width, image!.height,
  );
  const begin = (event: PointerEvent<HTMLDivElement>) => {
    if (!frozen || !image || !imageRef.current) return;
    origin.current = point(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    onSelection(rectangle(origin.current, origin.current));
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (origin.current && frozen && image) onSelection(rectangle(origin.current, point(event)));
  };
  const finish = (event: PointerEvent<HTMLDivElement>) => {
    move(event); origin.current = null;
  };

  return <div className={`viewport ${frozen ? 'selectable' : ''}`} aria-label="Game preview">
    {image ? <div className="image-surface" style={{ aspectRatio: `${image.width} / ${image.height}` }} onPointerDown={begin} onPointerMove={move}
      onPointerUp={finish} onPointerCancel={() => { origin.current = null; }}>
      <img ref={imageRef} src={image.url} alt={frozen ? 'Frozen game frame for selection' : stale ? 'Last good game frame' : 'Live game preview'}
        draggable={false} width={image.width} height={image.height} />
      {frozen && <svg className="selection-layer" viewBox={`0 0 ${image.width} ${image.height}`}
        aria-hidden="true" preserveAspectRatio="none">
        {selection && <rect x={selection.x} y={selection.y} width={selection.width} height={selection.height}
          fill="#e7c67b20" stroke="#f4d88f" strokeWidth="2" vectorEffect="non-scaling-stroke" />}
      </svg>}
      {!frozen && overlay && <svg className="selection-layer" viewBox={`0 0 ${image.width} ${image.height}`}
        aria-hidden="true" preserveAspectRatio="none">{overlay}</svg>}
    </div> : <div className="empty-view"><span className="empty-mark" aria-hidden="true">M</span>
      <h2>Your game, in view.</h2><p>Open Settings to connect a visible game window.<br />Capture and recognition work without keyboard output.</p>
    </div>}
  </div>;
}
