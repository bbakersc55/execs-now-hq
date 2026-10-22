import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NmiCardForm, NUDGE_AFTER, SHOW_AFTER } from "./NmiCardForm";

const NMI = "https://secure.nmi.com";
const FIELDS = ["ccnumber", "ccexp", "cvv"];

/** A stand-in for NMI's widget as it behaves (finding B3, 2026-10-22): its
 *  three frames sit in its shadow root, and it calls onFieldsAvailable only
 *  once each frame has answered with a "resize" message from NMI. */
const widget = vi.hoisted(() => ({
  loads: [] as string[], fieldsAvailable: 0, heard: new Set<string>(),
}));
vi.mock("@nmipayments/nmi-pay", () => ({
  mountNmiPayments: (box: HTMLElement, options: { onFieldsAvailable?: () => void }) => {
    const el = document.createElement("nmi-pay-widget");
    const root = el.attachShadow({ mode: "open" });
    for (const f of ["ccnumber", "ccexp", "cvv"]) {
      const frame = document.createElement("iframe");
      frame.setAttribute("data-cy", `iframe-${f}`);
      frame.addEventListener("load", () => widget.loads.push(f));
      root.appendChild(frame);
    }
    const hear = (e: MessageEvent) => {
      const d = e.data as { action?: string; fieldId?: string };
      if (!e.origin.includes("secure.nmi.com") || d?.action !== "resize" || !d.fieldId) return;
      widget.heard.add(d.fieldId);
      if (widget.heard.size === 3) { widget.fieldsAvailable += 1; options.onFieldsAvailable?.(); }
    };
    window.addEventListener("message", hear);
    box.appendChild(el);
    return { destroy: () => { window.removeEventListener("message", hear); el.remove(); } };
  },
}));

/** A frame's answer, as NMI sends it. */
function answer(fieldId: string) {
  window.dispatchEvent(new MessageEvent("message", {
    origin: NMI, source: window, data: { action: "resize", fieldId, height: 75 } }));
}

async function mounted() {
  render(<NmiCardForm publicKey="pub" amountCents={5000} payPath="/api/x/pay/"
    onDone={() => {}} />);
  await waitFor(() => expect(document.querySelector("nmi-pay-widget")).not.toBeNull());
}

describe("NMI's card fields come ready, or are shown anyway (finding B3)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    widget.loads = []; widget.fieldsAvailable = 0; widget.heard = new Set();
  });
  afterEach(() => vi.useRealTimers());

  it("leaves the widget alone when every frame answers", async () => {
    await mounted();
    FIELDS.forEach(answer);
    expect(widget.fieldsAvailable).toBe(1);
    await vi.advanceTimersByTimeAsync(SHOW_AFTER + 100);
    expect(widget.loads).toEqual([]);
    expect(widget.fieldsAvailable).toBe(1);
  });

  it("asks a frame that has not answered again, and only that one", async () => {
    await mounted();
    answer("ccnumber"); answer("cvv");
    await vi.advanceTimersByTimeAsync(NUDGE_AFTER + 50);
    expect(widget.loads).toEqual(["ccexp"]);
    answer("ccexp");
    expect(widget.fieldsAvailable).toBe(1);
    await vi.advanceTimersByTimeAsync(SHOW_AFTER);
    expect(widget.fieldsAvailable).toBe(1);
  });

  it("shows the fields after a few seconds when a frame never answers", async () => {
    await mounted();
    answer("cvv");
    await vi.advanceTimersByTimeAsync(SHOW_AFTER - 200);
    expect(widget.fieldsAvailable).toBe(0);
    await vi.advanceTimersByTimeAsync(300);
    expect(widget.fieldsAvailable).toBe(1);
    expect([...widget.heard].sort()).toEqual(["ccexp", "ccnumber", "cvv"]);
  });

  it("does nothing after the form is closed", async () => {
    const { unmount } = render(<NmiCardForm publicKey="pub" amountCents={5000}
      payPath="/api/x/pay/" onDone={() => {}} />);
    await waitFor(() => expect(document.querySelector("nmi-pay-widget")).not.toBeNull());
    unmount();
    await vi.advanceTimersByTimeAsync(SHOW_AFTER + 100);
    expect(widget.loads).toEqual([]);
    expect(widget.heard.size).toBe(0);
  });
});
