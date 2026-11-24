/** A signature drawn with a finger or a mouse, as a PNG. The owner's bundle's
 *  own copy (it may not import the app's components). */
import { useEffect, useRef } from "react";

export function SignaturePad({ drawn, onDrawn }: { drawn: string;
  onDrawn: (png: string) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    el.width = Math.max(1, Math.round(el.clientWidth * ratio));
    el.height = Math.max(1, Math.round(el.clientHeight * ratio));
    const ctx = el.getContext("2d");
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    ctx.lineWidth = 2.4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#1f2a33";
  }, []);

  const point = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - box.left, y: e.clientY - box.top };
  };
  const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx) return;
    drawing.current = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const { x, y } = point(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 0.1, y + 0.1);
    ctx.stroke();
  };
  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current) return;
    const ctx = canvas.current?.getContext("2d");
    if (!ctx) return;
    const { x, y } = point(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  };
  const up = () => {
    if (!drawing.current) return;
    drawing.current = false;
    if (canvas.current) onDrawn(canvas.current.toDataURL("image/png"));
  };
  const clear = () => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (el && ctx) {
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, el.width, el.height);
      ctx.restore();
    }
    onDrawn("");
  };
  return (
    <div>
      <canvas ref={canvas} className="ix-sig-pad" aria-label="Draw your signature here"
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={up} />
      <div className="ix-sig-row">
        <span className="ix-hint">{drawn ? "Drawn." : "Draw with your finger or mouse."}</span>
        <button type="button" className="ix-link" onClick={clear}>Clear</button>
      </div>
    </div>
  );
}
