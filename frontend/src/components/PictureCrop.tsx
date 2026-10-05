import { PointerEvent, useEffect, useRef, useState } from "react";

/** The crop is drawn at this size on screen and exported at twice it. */
const VIEW = 280;
const EXPORT = 512;
const MAX_ZOOM = 4;

export interface Crop { x: number; y: number; size: number }

/**
 * The square of the picture that is shown, in the picture's own pixels.
 *
 * `center` is the point of the picture at the middle of the crop. At zoom 1
 * the crop is the largest square that fits; zooming in shrinks it. The center
 * is held inside the picture so the crop never shows an empty edge.
 */
export function cropOf(width: number, height: number, zoom: number,
                       center: { x: number; y: number }): Crop {
  const size = Math.min(width, height) / Math.min(Math.max(zoom, 1), MAX_ZOOM);
  const half = size / 2;
  const hold = (value: number, max: number) => Math.min(Math.max(value, half), max - half);
  return { x: hold(center.x, width) - half, y: hold(center.y, height) - half, size };
}

/**
 * Choose the square of a picture to keep (UI 3 spec §6): drag to move, the
 * slider to zoom, arrow keys for both. Shown round, because that is how the
 * picture appears everywhere. One canvas, no library.
 */
export function PictureCrop({ file, busy, onCancel, onDone }: {
  file: File; busy?: boolean; onCancel: () => void; onDone: (picture: Blob) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [center, setCenter] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    const loading = new Image();
    loading.onload = () => {
      setImage(loading);
      setCenter({ x: loading.naturalWidth / 2, y: loading.naturalHeight / 2 });
    };
    loading.onerror = () => setFailed(true);
    loading.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const crop = image
    ? cropOf(image.naturalWidth, image.naturalHeight, zoom, center) : null;

  useEffect(() => {
    const context = canvas.current?.getContext("2d");
    if (!context || !image || !crop) return;
    context.clearRect(0, 0, VIEW, VIEW);
    context.drawImage(image, crop.x, crop.y, crop.size, crop.size, 0, 0, VIEW, VIEW);
  }, [image, crop?.x, crop?.y, crop?.size]);  // eslint-disable-line react-hooks/exhaustive-deps

  /** Move the picture under the crop by a distance on screen. */
  function move(dx: number, dy: number) {
    if (!image || !crop) return;
    const perPixel = crop.size / VIEW;
    const held = cropOf(image.naturalWidth, image.naturalHeight, zoom, {
      x: crop.x + crop.size / 2 - dx * perPixel, y: crop.y + crop.size / 2 - dy * perPixel,
    });
    setCenter({ x: held.x + held.size / 2, y: held.y + held.size / 2 });
  }

  function onPointerMove(event: PointerEvent) {
    if (!drag.current) return;
    move(event.clientX - drag.current.x, event.clientY - drag.current.y);
    drag.current = { x: event.clientX, y: event.clientY };
  }

  function save() {
    if (!image || !crop) return;
    const out = document.createElement("canvas");
    out.width = EXPORT;
    out.height = EXPORT;
    out.getContext("2d")?.drawImage(
      image, crop.x, crop.y, crop.size, crop.size, 0, 0, EXPORT, EXPORT);
    out.toBlob((blob) => { if (blob) onDone(blob); }, "image/jpeg", 0.92);
  }

  return (
    <>
      <div className="sheet-backdrop" onClick={onCancel} />
      <div className="move-dialog picture-crop" role="dialog" aria-modal="true"
        aria-label="Crop your picture"
        onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}>
        <h3>Crop your picture</h3>
        {failed ? (
          <p>That file could not be opened as a picture. Use a JPEG, PNG or WebP.</p>
        ) : (
          <>
            <p className="small muted">
              Drag the picture to move it and use the slider to zoom. It is shown round.
            </p>
            <canvas ref={canvas} width={VIEW} height={VIEW} tabIndex={0}
              aria-label="Your picture. Drag, or use the arrow keys, to move it."
              onPointerDown={(e) => {
                drag.current = { x: e.clientX, y: e.clientY };
                e.currentTarget.setPointerCapture?.(e.pointerId);
              }}
              onPointerMove={onPointerMove}
              onPointerUp={() => { drag.current = null; }}
              onPointerCancel={() => { drag.current = null; }}
              onKeyDown={(e) => {
                const step = { ArrowLeft: [16, 0], ArrowRight: [-16, 0],
                               ArrowUp: [0, 16], ArrowDown: [0, -16] }[e.key];
                if (step) { e.preventDefault(); move(step[0], step[1]); }
              }} />
            <label className="zoom small">Zoom
              <input type="range" aria-label="Zoom" min={1} max={MAX_ZOOM} step={0.05}
                value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
            </label>
          </>
        )}
        <div className="row tight">
          {!failed && (
            <button className="primary" disabled={!image || busy} onClick={save}>
              {busy ? "Saving…" : "Save picture"}
            </button>
          )}
          <button onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </>
  );
}
