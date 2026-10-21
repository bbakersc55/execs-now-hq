import { useEffect, useRef, useState } from "react";

import { PayResult, api } from "../lib/api";
import { dollars } from "../lib/money";
import { Banner } from "./ui";

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
    import("@nmipayments/nmi-pay").then(({ mountNmiPayments }) => {
      if (cancelled || !box.current) return;
      widget = mountNmiPayments(box.current, {
        tokenizationKey: publicKey, paymentMethods: ["card"],
        payButtonText: buttonText ?? `Pay ${dollars(amountCents)}`,
        onPay: async (event) => {
          if (use.current) return use.current(event.token);
          try {
            const result = await api.post<PayResult>(payPath, { payment_token: event.token });
            done.current(result);
            return result.status === "approved" ? true : result.message;
          } catch (e) {
            const message = (e as Error).message;
            done.current({ status: "failed", message, balance_cents: amountCents });
            return message;
          }
        },
      });
    }).catch(() => setLoadError("The card form could not be loaded. Please try again."));
    return () => { cancelled = true; widget?.destroy(); };
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
