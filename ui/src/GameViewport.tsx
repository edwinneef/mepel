import { useEffect, useRef, useState } from 'react';
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
  onStop?: () => void;
  stopDisabled?: boolean;
}

function GameSurface({ image, frozen, stale = false, selection, onSelection, overlay }: Props) {
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

export function GameViewport(props: Props) {
  const [zoom, setZoom] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { setZoom(0); }, [props.image?.sourceId]);
  useEffect(() => { if (expanded) dialog.current?.showModal(); }, [expanded]);
  const content = <div className="game-scroll" tabIndex={0} aria-label="Scrollable game picture">
    <div style={{ width: zoom && props.image ? props.image.width * zoom : '100%' }}><GameSurface {...props} /></div>
  </div>;
  return <>
    <div className="viewport-controls" aria-label="Game zoom controls">
      <button disabled={!props.image} aria-pressed={zoom === 0} onClick={() => setZoom(0)}>Fit</button>
      <button disabled={!props.image} aria-pressed={zoom === 1} onClick={() => setZoom(1)}>100%</button>
      <button disabled={!props.image} aria-pressed={zoom === 2} onClick={() => setZoom(2)}>200%</button>
      <button disabled={!props.image} onClick={() => setExpanded(true)}>Expand game</button>
    </div>
    {content}
    {expanded && <dialog ref={dialog} className="game-dialog" aria-label="Expanded game" onClose={() => setExpanded(false)}>
      <header><strong>Game picture</strong><div className="game-dialog-actions">
        {props.onStop && <button className="stop-button" disabled={props.stopDisabled} onClick={props.onStop}>Stop <kbd>F8</kbd></button>}
        <button onClick={() => dialog.current?.close()}>Close expanded game</button>
      </div></header>
      {content}
    </dialog>}
  </>;
}
