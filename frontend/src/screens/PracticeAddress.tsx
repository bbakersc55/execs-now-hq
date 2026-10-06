import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Field, Pill } from "../components/ui";
import { GmailStatus, Me, api } from "../lib/api";

type Which = "separate" | "own";
type Kind = "alias" | "inbox";

/** `info@` at the domain of the address given, as a starting suggestion. */
function suggested(email: string) {
  const domain = email.split("@")[1] ?? "";
  return domain ? `info@${domain}` : "";
}

/**
 * The practice address: who app mail is from (beta feedback, 2026-10-05).
 *
 * It used to be `info@<domain>`, set when the practice was created and
 * unchangeable, so a new owner was sent to Gmail to create an address they had
 * not chosen. Now it is three questions, asked **before** Connect, and the
 * owner's own email is an allowed answer: a separate address is recommended,
 * not required, because for some owners adding an alias is the step that stops
 * them.
 *
 * Practice owner only. Saving runs the same "Send mail as" check as connecting.
 */
export function PracticeAddress({ me, status, onSaved }: {
  me: Me; status: GmailStatus;
  onSaved: (next: GmailStatus, message: { ok?: string; problem?: string }) => void;
}) {
  const qc = useQueryClient();
  // The account they will connect is the one they sign in with.
  const [mine, setMine] = useState(status.email_address || me.email);
  const current = status.alias;
  const isOwn = current.toLowerCase() === mine.trim().toLowerCase();
  const [which, setWhich] = useState<Which>(isOwn ? "own" : "separate");
  const [address, setAddress] = useState(isOwn ? suggested(mine) : current);
  const [kind, setKind] = useState<Kind>("alias");
  // Asked up front until it is working; after that it is a setting to change.
  const [open, setOpen] = useState(!status.connected || !status.alias_verified);

  const chosen = (which === "own" ? mine : address).trim().toLowerCase();
  const save = useMutation({
    mutationFn: () => api.post<GmailStatus>("/api/gmail-connection/practice-address/",
                                            { address: chosen }),
    onSuccess: (next) => {
      qc.setQueryData(["gmail-connection"], next);
      setOpen(!next.connected || !next.alias_verified);
      onSaved(next, next.verify_error ? { problem: next.verify_error }
        : next.connected ? { ok: `${next.alias} is verified. App mail will send as it.` }
        : { ok: `Saved. ${next.alias} will be checked when you connect Gmail below.` });
    },
    onError: (e: Error) => onSaved(status, { problem: e.message }),
  });

  if (!open) {
    return (
      <Card title="Practice address"
        actions={<button className="ghost" onClick={() => setOpen(true)}>Change</button>}>
        <p>
          <strong>{current}</strong>{" "}
          {isOwn && <Pill>your own email</Pill>}
        </p>
        <p className="muted small">
          Clients see this as the sender of digests, sign-in links and other mail the app
          sends for the practice.
        </p>
      </Card>
    );
  }

  return (
    <Card title="Practice address">
      <p className="small muted" style={{ marginTop: 0 }}>
        The address clients see as the sender of digests, sign-in links and other mail the
        app sends for the practice. Answer these before you connect Gmail. Currently:{" "}
        <strong>{current}</strong>.
      </p>

      <Field label="1. What is your email?">
        <input type="email" aria-label="What is your email?" value={mine}
          onChange={(e) => setMine(e.target.value)} style={{ maxWidth: "24rem" }} />
      </Field>
      <p className="small muted">This is the Google account you will connect below.</p>

      <fieldset className="questions">
        <legend>
          2. Do you want your practice address to be something different, like info@ or
          helpdesk@, or do you want your own email to be the practice address?
        </legend>
        <label className="choice">
          <input type="radio" name="which" checked={which === "separate"}
            onChange={() => setWhich("separate")} />
          <span>A separate practice address <Pill kind="ok">recommended</Pill></span>
        </label>
        {which === "separate" && (
          <div className="indent">
            <input type="email" aria-label="Practice address" value={address}
              placeholder={suggested(mine) || "info@yourpractice.com"}
              onChange={(e) => setAddress(e.target.value)} style={{ maxWidth: "24rem" }} />
            <p className="small muted">
              Most practices use info@. Clients then hear from the practice, and the address
              stays the same whoever is on the team.
            </p>
          </div>
        )}
        <label className="choice">
          <input type="radio" name="which" checked={which === "own"}
            onChange={() => setWhich("own")} />
          <span>Use my own email</span>
        </label>
        {which === "own" && (
          <p className="small muted indent">
            Nothing to set up in Gmail. Digests and sign-in links will come from{" "}
            {mine.trim() || "your address"}. You can change this later.
          </p>
        )}
      </fieldset>

      {which === "separate" && (
        <fieldset className="questions">
          <legend>3. Do you want a separate inbox or an alias?</legend>
          <Banner kind="info">
            A <strong>separate inbox</strong> is an extra charge with Google or Microsoft,
            and one more inbox to manage. An <strong>alias</strong> costs nothing extra and
            is not a separate inbox to manage: mail sent to it arrives in your own inbox.
          </Banner>
          <label className="choice">
            <input type="radio" name="kind" checked={kind === "alias"}
              onChange={() => setKind("alias")} />
            <span>An alias</span>
          </label>
          <label className="choice">
            <input type="radio" name="kind" checked={kind === "inbox"}
              onChange={() => setKind("inbox")} />
            <span>A separate inbox</span>
          </label>

          {kind === "alias" ? (
            <div className="indent small">
              <p><strong>To add the alias (Google Workspace):</strong></p>
              <ol>
                <li>Sign in to the Google Admin console (admin.google.com) as an
                  administrator and open <em>Directory → Users</em>.</li>
                <li>Click your name, open <em>User information</em>, and under{" "}
                  <em>Alternate email addresses</em> add {address.trim() || "the alias"}.
                  Save. It can take a few minutes to start working.</li>
                <li>In Gmail, open <em>Settings → See all settings → Accounts</em> and,
                  beside <em>Send mail as</em>, choose <em>Add another email address</em>.
                  Enter the practice's name and the alias, and leave{" "}
                  <em>Treat as an alias</em> ticked.</li>
                <li>If Gmail sends a confirmation email, open it and click the link.</li>
                <li>Come back here and press Save. The app checks that Gmail lists it.</li>
              </ol>
              <p className="muted">
                An alias at your own domain needs Google Workspace. With a free @gmail.com
                account, use your own email as the practice address instead.
              </p>
            </div>
          ) : (
            <div className="indent small">
              <p><strong>What works today with a separate inbox:</strong></p>
              <ul>
                <li>The app can <strong>send from it</strong> once it is in your Gmail{" "}
                  <em>Send mail as</em> list: in Gmail, <em>Settings → See all settings →
                  Accounts → Send mail as → Add another email address</em>, enter that
                  inbox's address, and confirm from the email Gmail sends to that inbox.
                  For an inbox outside your Google Workspace, Gmail also asks for its
                  sending (SMTP) details.</li>
                <li><strong>Replies sent to that inbox will not appear in client
                  records.</strong> The app reads only the Gmail account you connect.
                  Connecting a second account is planned and not built yet.</li>
                <li>The app connects to Google only today. A Microsoft 365 inbox cannot
                  be connected.</li>
              </ul>
            </div>
          )}
        </fieldset>
      )}

      <div className="row tight">
        <button className="primary" disabled={!chosen || save.isPending}
          onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : `Save ${chosen || "the practice address"}`}
        </button>
        {status.connected && status.alias_verified && (
          <button onClick={() => setOpen(false)}>Cancel</button>
        )}
      </div>
    </Card>
  );
}
