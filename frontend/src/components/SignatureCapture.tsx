import { useEffect, useRef } from "react";

import { CapturedSignature } from "../lib/api";

/**
 * A signature, typed or drawn (e-signature, 2026-10-29), with the consent
 * line that must be ticked before it counts. The signing page and the
 * countersign panel both use it. Typed is shown in the same cursive face the
 * signed PDF embeds; drawn is a PNG of the pad, as drawn.
 */
export function SignatureCapture({ value, onChange, consent, agreed, onAgree }: {
  value: CapturedSignature;
  onChange: (next: CapturedSignature) => void;
  consent: string;
  agreed: boolean;
  onAgree: (agreed: boolean) => void;
}) {
  return (
    <div className="sig-capture">
      <div className="sig-tabs" role="group" aria-label="How to sign">
        {(["typed", "drawn"] as const).map((method) => (
          <button key={method} type="button" aria-pressed={value.method === method}
            className={value.method === method ? "small primary" : "small"}
            onClick={() => onChange({ ...value, method })}>
            {method === "typed" ? "Type it" : "Draw it"}
          </button>
        ))}
      </div>
      {value.method === "typed" ? (
        <>
          <label className="small">Your name, as your signature
            <input aria-label="Type your signature" value={value.typed} maxLength={200}
              autoComplete="name"
              onChange={(e) => onChange({ ...value, typed: e.target.value })} />
          </label>
          <div className="sig-typed" aria-label="Your signature as it will appear">
            {value.typed || " "}</div>
        </>
      ) : (
        <SignaturePad drawn={value.drawn} onDrawn={(drawn) => onChange({ ...value, drawn })} />
      )}
      <label className="sig-consent">
        <input type="checkbox" checked={agreed} aria-label="I agree to sign electronically"
          onChange={(e) => onAgree(e.target.checked)} />
        <span>{consent}</span>
      </label>
    </div>
  );
}

/** Whether a capture has something to sign with. */
export function hasSignature(value: CapturedSignature): boolean {
  return value.method === "typed" ? value.typed.trim().length > 0 : value.drawn.length > 0;
}

function SignaturePad({ drawn, onDrawn }: { drawn: string; onDrawn: (png: string) => void }) {
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
    ctx.strokeStyle = "#0a3a65";
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
      <canvas ref={canvas} className="sig-pad" aria-label="Draw your signature here"
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={up} />
      <div className="spread" style={{ marginTop: "var(--s1)" }}>
        <span className="small muted">{drawn ? "Drawn." : "Draw with your finger or mouse."}</span>
        <button type="button" className="small ghost" onClick={clear}>Clear</button>
      </div>
    </div>
  );
}
