import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { PageHead } from "../components/shell";
import { api, Me } from "../lib/api";
import { hasPersonal } from "../lib/personal";

/**
 * U2 (2026-10-20): one door for every import. Melissa looked for the bank
 * import and found the contacts one. Each choice opens the importer that was
 * already there, whose own first step picks the account; the old ways in
 * (Contacts → Import, Finance → Import, Personal → Import) stay.
 */
export interface ImportChoice { key: string; label: string; takes: string; to: string }

const STATEMENT = "CSV, OFX, QFX, QBO or PDF";

/** What this person can import, in the order a new practice needs them. Each
 *  is shown only where its importer would let them in. */
export function importChoices(me: Me | undefined): ImportChoice[] {
  const role = me?.role;
  const owner = role === "FF";
  const out: ImportChoice[] = [];
  if (owner || role === "VA") {
    out.push({ key: "contacts", label: "Contacts and companies", to: "/import/contacts",
      takes: "A CSV of people and their companies, from a spreadsheet or another CRM." });
  }
  if (owner) {
    out.push({ key: "business", label: "A business bank or card statement",
      to: "/finance/import",
      takes: `A statement for one of the practice's accounts, into the books: ${STATEMENT}.` });
  }
  if (owner && hasPersonal(me) && !me?.acting) {
    out.push({ key: "personal", label: "A personal bank or card statement",
      to: "/finance/personal/import",
      takes: `A statement for one of your own accounts, into your personal ledger: ${
        STATEMENT}.` });
  }
  if (owner) {
    out.push({ key: "meetings", label: "Meeting notes from Google Drive",
      to: "/meetings",
      takes: "No file to choose: the Gemini notes in a Drive folder you pick, read into the "
        + "meeting queue for review." });
  }
  return out;
}

export function ImportDoor() {
  const me = useQuery<Me>({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  const choices = importChoices(me.data);
  return (
    <>
      <PageHead title="Import" sub="What are you importing?" />
      {me.data && (
        <ul className="import-door" aria-label="What are you importing?">
          {choices.map((c) => (
            <li key={c.key}>
              <Link to={c.to}>
                <strong>{c.label}</strong>
                <span>{c.takes}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
