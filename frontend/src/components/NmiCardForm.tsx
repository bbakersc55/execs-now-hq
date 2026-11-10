import { useEffect, useRef, useState } from "react";

import { CardForm, PayResult, api } from "../lib/api";
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

interface CardFormProps {
  publicKey: string; amountCents: number; payPath: string;
  onDone: (result: PayResult) => void;
  /** Saving a card rather than paying (P4 part 4): its own button and its own
   *  use of the token, which returns true or the sentence to show. */
  buttonText?: string; onToken?: (token: string) => Promise<true | string>;
  /** Which form (2026-11-10): the server's choice, from NMI_API_HOST. */
  form?: CardForm;
}

/** The token posted to the pay path, and the answer as a PayResult. */
async function postToken(payPath: string, token: string, amountCents: number): Promise<PayResult> {
  try {
    return await api.post<PayResult>(payPath, { payment_token: token });
  } catch (e) {
    return { status: "failed", message: (e as Error).message, balance_cents: amountCents };
  }
}

/**
 * NMI's card fields (P4 parts 2 and 3), mounted with the practice's public
 * key fetched at runtime. The card is typed into the gateway's own frames;
 * this app only ever receives a one-time token, which is posted to
 * `payPath`. The form is loaded only when someone pays: NMI's Payment
 * Component on NMI's own host, or Collect.js from the processor's
 * white-label host, as the server says (`form`).
 */
export function NmiCardForm(props: CardFormProps) {
  return props.form?.kind === "collect"
    ? <CollectCardForm {...props} scriptUrl={props.form.script_url} />
    : <ComponentCardForm {...props} />;
}

function ComponentCardForm({ publicKey, amountCents, payPath, onDone, buttonText, onToken }:
  CardFormProps) {
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
          const result = await postToken(payPath, event.token, amountCents);
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


// ------------------------------------------------------------ Collect.js

interface CollectResponse { token: string }
interface CollectJs {
  configure: (config: Record<string, unknown>) => void;
  startPaymentRequest: () => void;
}
declare global { interface Window { CollectJS?: CollectJs } }

/** How long Collect.js waits on the gateway for a token (ms). */
export const COLLECT_TIMEOUT = 15000;

/** Collect.js from `url` with `key`, once per page: it reads the key from
 *  its own script tag, so another key (another practice's) loads it again. */
function loadCollect(url: string, key: string): Promise<CollectJs> {
  const present = document.querySelector<HTMLScriptElement>("script[data-collect-js]");
  if (present && present.src === url && present.dataset.tokenizationKey === key
      && window.CollectJS)
    return Promise.resolve(window.CollectJS);
  present?.remove();
  delete window.CollectJS;
  return new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = url;
    tag.dataset.collectJs = "";
    tag.dataset.tokenizationKey = key;
    tag.dataset.variant = "inline";
    tag.async = true;
    tag.onload = () => window.CollectJS ? resolve(window.CollectJS) : reject(new Error("no CollectJS"));
    tag.onerror = () => reject(new Error("Collect.js did not load"));
    document.head.appendChild(tag);
  });
}

let collectSeq = 0;

/**
 * The card fields from Collect.js (2026-11-10), for a host NMI's Payment
 * Component does not serve: the processor's white-label host. The card is
 * typed into the gateway's frames inside the three boxes below; Pay asks
 * Collect.js for a one-time token, which goes to the same pay path and the
 * same v5 sale as the component's. Nothing here reads or carries card data.
 */
function CollectCardForm({ publicKey, amountCents, payPath, onDone, buttonText, onToken,
  scriptUrl }: CardFormProps & { scriptUrl: string }) {
  const [ids] = useState(() => {
    collectSeq += 1;
    return { ccnumber: `cj-ccnumber-${collectSeq}`, ccexp: `cj-ccexp-${collectSeq}`,
             cvv: `cj-cvv-${collectSeq}` };
  });
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const collect = useRef<CollectJs | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  const use = useRef(onToken);
  use.current = onToken;

  useEffect(() => {
    if (!publicKey) return;
    let cancelled = false;
    setReady(false);
    loadCollect(scriptUrl, publicKey).then((cj) => {
      if (cancelled) return;
      collect.current = cj;
      cj.configure({
        variant: "inline",
        fields: {
          ccnumber: { selector: `#${ids.ccnumber}`, title: "Card number",
                      placeholder: "Card number" },
          ccexp: { selector: `#${ids.ccexp}`, title: "Expiry", placeholder: "MM / YY" },
          cvv: { selector: `#${ids.cvv}`, title: "Security code", placeholder: "CVV" },
        },
        fieldsAvailableCallback: () => { if (!cancelled) setReady(true); },
        timeoutDuration: COLLECT_TIMEOUT,
        timeoutCallback: () => {
          if (cancelled) return;
          setBusy(false);
          setProblem("The card processor did not answer. Check the card details and try again.");
        },
        validationCallback: (_field: string, valid: boolean, message: string) => {
          if (!cancelled && !valid && message) setProblem(message);
        },
        callback: async (response: CollectResponse) => {
          if (cancelled) return;
          setProblem("");
          if (use.current) {
            const answer = await use.current(response.token);
            setBusy(false);
            if (answer !== true) setProblem(answer);
            return;
          }
          const result = await postToken(payPath, response.token, amountCents);
          setBusy(false);
          if (result.status !== "approved" && result.status !== "unknown")
            setProblem(result.message);
          done.current(result);
        },
      });
    }).catch(() => { if (!cancelled) setProblem("The card form could not be loaded. Please try again."); });
    return () => { cancelled = true; };
  }, [publicKey, scriptUrl, payPath, amountCents, ids]);

  const start = () => {
    if (!collect.current || busy) return;
    setProblem("");
    setBusy(true);
    collect.current.startPaymentRequest();
  };

  return (
    <>
      {problem && <Banner kind="bad">{problem}</Banner>}
      <div data-testid="card-form" className="collect-fields">
        <label className="small muted" htmlFor={ids.ccnumber}>Card number</label>
        <div id={ids.ccnumber} className="collect-field" />
        <div className="row tight">
          <div style={{ flex: 1 }}>
            <label className="small muted" htmlFor={ids.ccexp}>Expiry</label>
            <div id={ids.ccexp} className="collect-field" />
          </div>
          <div style={{ flex: 1 }}>
            <label className="small muted" htmlFor={ids.cvv}>Security code</label>
            <div id={ids.cvv} className="collect-field" />
          </div>
        </div>
        {!ready && !problem && <p className="small muted">Loading the card form…</p>}
        <button type="button" className="primary" disabled={!ready || busy} onClick={start}>
          {busy ? "Working…" : buttonText ?? `Pay ${dollars(amountCents)}`}</button>
      </div>
      <p className="small muted" style={{ marginBottom: 0 }}>
        Your card details go straight to the card processor and never to this app.
      </p>
    </>
  );
}
