import { useEffect, useRef, useState, useSyncExternalStore } from "react";

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
  /** Where to report a form that would not load (2026-11-13): the server
   *  tells the practice owner and answers the sentence the payer sees. */
  failurePath?: string;
}

/** What the payer reads when the form can't load, until the server answers
 *  with the practice's own words (or if it can't be reached). */
export const FORM_FAILED = "The card form could not be loaded, so nothing was charged or "
  + "saved. Please reload this page in a few minutes.";
/** How long Collect.js has to show its fields before the form counts as
 *  not loaded (ms). */
export const FIELDS_WITHIN = 20000;

/**
 * A form that would not load is never silent (2026-11-13): the payer is
 * told at once, and the server is told once per form, which tells the
 * practice owner and answers with the words to show instead.
 */
function useFailure(failurePath: string | undefined, kind: string, host: string) {
  const [message, setMessage] = useState("");
  const sent = useRef(false);
  const fail = (reason: string) => {
    setMessage((said) => said || FORM_FAILED);
    if (sent.current || !failurePath) return;
    sent.current = true;
    api.post<{ message?: string }>(failurePath, { form: kind, host,
                                                  reason: (reason || "").slice(0, 300) })
      .then((answer) => { if (answer?.message) setMessage(answer.message); })
      .catch(() => { /* the payer already has FORM_FAILED */ });
  };
  return [message, fail] as const;
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

function ComponentCardForm({ publicKey, amountCents, payPath, onDone, buttonText, onToken,
  failurePath }: CardFormProps) {
  const box = useRef<HTMLDivElement>(null);
  const [loadError, fail] = useFailure(failurePath, "component", "secure.nmi.com");
  const failed = useRef(fail);
  failed.current = fail;
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
      try {
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
      } catch (e) {
        failed.current(`NMI's Payment Component did not start: ${(e as Error).message}`);
        return;
      }
      if (!ready) unwatch = watchFields(box.current, () => ready);
    }).catch((e) => {
      if (!cancelled) failed.current(`NMI's Payment Component did not load: ${(e as Error).message}`);
    });
    return () => { cancelled = true; unwatch(); widget?.destroy(); };
  }, [publicKey, amountCents, payPath, buttonText]);

  return (
    <>
      {loadError && <div role="alert"><Banner kind="bad">{loadError}</Banner></div>}
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

/**
 * The only data attributes the script tag carries (2026-11-13). Collect.js
 * builds its configuration from **every** data attribute on its own tag and
 * refuses the page if one is not a setting it knows: a `data-collect-js`
 * marker became `collectJs` and stopped every live pay page with "You
 * provided too many fields. Unexpected fields for collectJs". Both are on
 * Collect.js's own list (`acceptableProperties` in its Config.js).
 */
export const COLLECT_TAG_DATA = ["tokenizationKey", "variant"] as const;

/** The tag that loaded Collect.js, found by its address alone. */
function collectTag(): HTMLScriptElement | null {
  return document.querySelector<HTMLScriptElement>('script[src$="/token/Collect.js"]');
}

/** Collect.js from `url` with `key`, once per page: it reads the key from
 *  its own script tag, so another key (another practice's) loads it again.
 *  A refusal inside the script (it throws as it starts, and then defines
 *  nothing) is caught and comes back as the reason. */
function loadCollect(url: string, key: string): Promise<CollectJs> {
  const present = collectTag();
  if (present && present.src === url && present.dataset.tokenizationKey === key
      && window.CollectJS)
    return Promise.resolve(window.CollectJS);
  present?.remove();
  delete window.CollectJS;
  return new Promise((resolve, reject) => {
    let said = "";
    // The script runs, and throws if it will, just before its load event.
    const hear = (e: ErrorEvent) => { said = e.message || said; };
    window.addEventListener("error", hear);
    const tag = document.createElement("script");
    tag.src = url;
    tag.dataset.tokenizationKey = key;
    tag.dataset.variant = "inline";
    tag.async = true;
    tag.onload = () => {
      window.removeEventListener("error", hear);
      if (window.CollectJS) resolve(window.CollectJS);
      else reject(new Error(`Collect.js loaded but did not start${said ? `: ${said}` : ""}`));
    };
    tag.onerror = () => {
      window.removeEventListener("error", hear);
      reject(new Error(`Collect.js could not be fetched from ${url}`));
    };
    document.head.appendChild(tag);
  });
}

/**
 * Collect.js is one per page: one configuration, one set of fields. The
 * form opened last owns it (a client paying an invoice while "Save a card"
 * is open); an earlier one waits, says so, and takes it back when the later
 * one closes.
 */
const collectStack: number[] = [];
const collectHeard = new Set<() => void>();
const collectOwner = () => collectStack[collectStack.length - 1] ?? 0;
function onCollectOwner(listener: () => void) {
  collectHeard.add(listener);
  return () => { collectHeard.delete(listener); };
}
function claimCollect(id: number) {
  collectStack.push(id);
  collectHeard.forEach((l) => l());
  return () => {
    const at = collectStack.indexOf(id);
    if (at >= 0) collectStack.splice(at, 1);
    collectHeard.forEach((l) => l());
  };
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
  scriptUrl, failurePath }: CardFormProps & { scriptUrl: string }) {
  const [ids] = useState(() => {
    collectSeq += 1;
    return { me: collectSeq, ccnumber: `cj-ccnumber-${collectSeq}`,
             ccexp: `cj-ccexp-${collectSeq}`, cvv: `cj-cvv-${collectSeq}` };
  });
  const host = (() => { try { return new URL(scriptUrl).host; } catch { return ""; } })();
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [notLoaded, fail] = useFailure(failurePath, "collect", host);
  const failed = useRef(fail);
  failed.current = fail;
  const collect = useRef<CollectJs | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  const use = useRef(onToken);
  use.current = onToken;

  useEffect(() => claimCollect(ids.me), [ids.me]);
  const owns = useSyncExternalStore(onCollectOwner, collectOwner) === ids.me;

  useEffect(() => {
    if (!publicKey || !owns) return;
    let cancelled = false;
    setReady(false);
    collect.current = null;
    // Fields that never come are a form that did not load, whatever the cause.
    const late = window.setTimeout(() => {
      if (!cancelled) failed.current(
        `The card fields did not appear within ${FIELDS_WITHIN / 1000} seconds.`);
    }, FIELDS_WITHIN);
    loadCollect(scriptUrl, publicKey).then((cj) => {
      if (cancelled) return;
      try {
        cj.configure({
          variant: "inline",
          fields: {
            ccnumber: { selector: `#${ids.ccnumber}`, title: "Card number",
                        placeholder: "Card number" },
            ccexp: { selector: `#${ids.ccexp}`, title: "Expiry", placeholder: "MM / YY" },
            cvv: { selector: `#${ids.cvv}`, title: "Security code", placeholder: "CVV" },
          },
          fieldsAvailableCallback: () => {
            if (cancelled) return;
            window.clearTimeout(late);
            setReady(true);
          },
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
        collect.current = cj;
      } catch (e) {
        window.clearTimeout(late);
        failed.current(`Collect.js refused the form's settings: ${(e as Error).message}`);
      }
    }).catch((e) => {
      window.clearTimeout(late);
      if (!cancelled) failed.current((e as Error).message);
    });
    return () => { cancelled = true; window.clearTimeout(late); };
  }, [publicKey, scriptUrl, payPath, amountCents, ids, owns]);

  const start = () => {
    if (!collect.current || busy) return;
    setProblem("");
    setBusy(true);
    collect.current.startPaymentRequest();
  };

  if (!owns) {
    return (
      <p className="small muted" data-testid="card-form-waiting">
        Another card form is open on this page. Close it to use this one.
      </p>
    );
  }
  return (
    <>
      {notLoaded && <div role="alert"><Banner kind="bad">{notLoaded}</Banner></div>}
      {problem && !notLoaded && <Banner kind="bad">{problem}</Banner>}
      <div data-testid="card-form" className="collect-fields" hidden={!!notLoaded}>
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
