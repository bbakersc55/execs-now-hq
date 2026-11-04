import { Banner } from "./ui";

/**
 * While a feed editor reads its connection for the people, properties or
 * stages it offers (Track, HubSpot, Besty), a spinner says so; if the read
 * fails, a plain error says that. The measure itself never waits: its menu
 * comes with the KPI's own data (SkyRun Park City, 2026-11-04).
 */
export function ConnectionRead({ source, what, pending, error,
  meanwhile = "The total can be saved meanwhile.",
  still = "The measure can still be saved for the total." }: {
  /** "Track", "HubSpot", "Besty". */
  source: string;
  /** What is being read, as a plural noun: "properties", "owners and stages". */
  what: string;
  pending: boolean;
  error: unknown;
  /** What can be done while it is read, and after it failed. */
  meanwhile?: string;
  still?: string;
}) {
  if (pending) {
    return (
      <p className="small muted row tight" role="status" style={{ margin: 0 }}>
        <span className="spinner" aria-hidden="true" />
        Reading the {what} from {source}…{meanwhile ? ` ${meanwhile}` : ""}</p>
    );
  }
  if (error) {
    return (
      <div role="alert"><Banner kind="bad">{source}'s {what} could not be read:{" "}
        {error instanceof Error ? error.message : String(error)}{still ? ` ${still}` : ""}
      </Banner></div>
    );
  }
  return null;
}
