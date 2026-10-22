import { useEffect, useRef, useState } from "react";

import { PayResult, api } from "../lib/api";
import { dollars } from "../lib/money";
import { Banner } from "./ui";

const FIELDS = ["ccnumber", "ccexp", "cvv"] as const;
const NMI_ORIGIN = "https://secure.nmi.com";
/** When a frame that has not answered is asked again, and when the fields are
 *  shown regardless (ms). */
export const NUDGE_AFTER = 1500;
export const SHOW_AFTER = 5000;

/**
 * NMI's widget keeps its wheel up until each of its three card frames has
 * answered its styling message with a "resize" message, and only then calls
 * `onFieldsAvailable`. The styling message goes out on the frame's load
 * event; when NMI's page is not yet listening it is lost, that frame never
 * answers, and the wheel stays over fields that already take typing (finding
 * B3, 2026-10-22: three of six sandbox loads in headless Chrome). So a frame
 * that has not answered gets its load event again, which sends the styling
 * again; and if the fields are still not ready after SHOW_AFTER, the widget is
 * told the missing frames are there, which takes the wheel down and shows its
 * Pay button. Nothing here reads or carries card data.
 */
function watchFields(box: HTMLElement, isReady: () => boolean) {
  const answered = new Set<string>();
  const hear = (e: MessageEvent) => {
    const d = e.data as { action?: string; fieldId?: string } | null;
    if (e.origin === NMI_ORIGIN && d && d.action === "resize" && d.fieldId)
      answered.add(d.fieldId);
  };
  window.addEventListener("message", hear);
  const frames = () => {
    const widget = box.firstElementChild;
    const root = widget?.shadowRoot ?? widget;
    return [...(root?.querySelectorAll<HTMLIFrameElement>("iframe") ?? [])];
  };
  const fieldOf = (frame: HTMLIFrameElement) =>
    (frame.getAttribute("data-cy") ?? "").replace("iframe-", "");
  const silent = () => FIELDS.filter((f) => !answered.has(f)
    && frames().some((frame) => fieldOf(frame) === f));
  const nudge = window.setTimeout(() => {
    if (isReady()) return;
    for (const frame of frames())
      if (silent().includes(fieldOf(frame) as typeof FIELDS[number]))
        frame.dispatchEvent(new Event("load"));
  }, NUDGE_AFTER);
  const show = window.setTimeout(() => {
    if (isReady()) return;
    for (const fieldId of silent())
      window.dispatchEvent(new MessageEvent("message", {
        origin: NMI_ORIGIN, data: { action: "resize", fieldId, height: 75 } }));
  }, SHOW_AFTER);
  return () => {
    window.clearTimeout(nudge);
    window.clearTimeout(show);
    window.removeEventListener("message", hear);
  };
}

/**
 * NMI's card fields (P4 parts 2 and 3), mounted with the practice's public
 * key fetched at runtime. The card is typed into NMI's own frames; this app
 * only ever receives a one-time token, which is posted to `payPath`. The
 * component is loaded only when someone pays.
 */
export function NmiCardForm({ publicKey, amountCents, payPath, onDone, buttonText, onToken }: {
  publicKey: string; amountCents: number; payPath: string;
  onDone: (result: PayResult) => void;
  /** Saving a card rather than paying (P4 part 4): its own button and its own
   *  use of the token, which returns true or the sentence to show. */
  buttonText?: string; onToken?: (token: string) => Promise<true | string>;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [loadError, setLoadError] = useState("");
  const done = useRef(onDone);
  done.current = onDone;
  const use = useRef(onToken);
  use.current = onToken;

  useEffect(() => {
    if (!publicKey || !box.current) return;
    let widget: { destroy: () => void } | null = null;
    let cancelled = false;
    let ready = false;
    let unwatch = () => {};
    import("@nmipayments/nmi-pay").then(({ mountNmiPayments }) => {
      if (cancelled || !box.current) return;
      widget = mountNmiPayments(box.current, {
        tokenizationKey: publicKey, paymentMethods: ["card"],
        payButtonText: buttonText ?? `Pay ${dollars(amountCents)}`,
        onFieldsAvailable: () => { ready = true; unwatch(); },
        onPay: async (event) => {
          if (use.current) return use.current(event.token);
          // The answer goes back to NMI's form first, and the page hears it
          // after: a page that closed the form while it was still waiting on
          // this call left it, and the list behind it, spinning (finding B5).
          let result: PayResult;
          try {
            result = await api.post<PayResult>(payPath, { payment_token: event.token });
          } catch (e) {
            result = { status: "failed", message: (e as Error).message,
                       balance_cents: amountCents };
          }
          setTimeout(() => done.current(result), 0);
          return result.status === "approved" ? true : result.message;
        },
      });
      if (!ready) unwatch = watchFields(box.current, () => ready);
    }).catch(() => setLoadError("The card form could not be loaded. Please try again."));
    return () => { cancelled = true; unwatch(); widget?.destroy(); };
  }, [publicKey, amountCents, payPath, buttonText]);

  return (
    <>
      {loadError && <Banner kind="bad">{loadError}</Banner>}
      <div ref={box} data-testid="card-form" />
      <p className="small muted" style={{ marginBottom: 0 }}>
        Your card details go straight to the card processor and never to this app.
      </p>
    </>
  );
}
