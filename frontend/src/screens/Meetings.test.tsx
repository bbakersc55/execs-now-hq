import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MeetingProposal } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Meetings } from "./Meetings";

const ID = "p1";

const HEALTH = { connected: true, google_connected: true, drive_access: true,
                 drive_account: "bryan@x.test",
                 folder_id: "folder-1", folder_name: "Meeting notes",
                 last_polled_at: "2026-09-22T09:00:00Z", last_error: "",
                 has_cursor: true, files_pending: 0, files_failed: 0, files_skipped: 1,
                 backfill: null };

/** Not connected, at each of the three points the flow can be stopped at. */
const UNCONNECTED = { ...HEALTH, connected: false, folder_id: "", folder_name: "",
                      last_polled_at: null, has_cursor: false };

/** What the owner's own folder actually looked like: six months of notes the
 *  poller could not see. */
const PAST = { folder_name: "Meet Recordings", readable_here: 167,
               readable_in_subfolders: 0, subfolders: [], readable_total: 167,
               outstanding: 167, oldest: "2026-03-30", newest: "2026-09-11",
               per_note_usd: "0.0575", per_note_is_measured: false,
               estimate_usd: "9.60", minutes: 56 };

function aBackfill(overrides: Record<string, unknown> = {}) {
  return { id: "b1", scope: "all", since: null, state: "running", running: true,
           planned: 167, done: 42, skipped: 1, failed: 0, remaining: 124,
           estimated_cost_usd: "9.60", cost_usd: "2.410000", last_error: "",
           started_at: "2026-09-22T10:00:00Z", finished_at: null, ...overrides };
}

function aProposal(overrides: Partial<MeetingProposal> = {}): MeetingProposal {
  return {
    id: ID, state: "pending", title: "Acme operations review",
    meeting_date: "2026-09-20",
    proposed_summary: "Dispatch and margin reporting came up.",
    summary: "", summary_discarded: false,
    source_file: { id: "f1", name: "Acme notes", mime_type: "application/vnd.google-apps.document",
                   state: "parsed", skip_reason: "", error: "",
                   owner_email: "bryan@x.test", web_view_link: "https://d/f1",
                   fetched_at: "2026-09-22T09:00:00Z" },
    meeting: null, counts: { pending: 2, approved: 0, rejected: 0 },
    items: [
      { id: "i1", kind: "participant", state: "pending",
        source_excerpt: "Attendees: Dana Reyes (dana@acme.invalid)",
        position: 0, created_record_type: "", created_record_id: null,
        actioned_at: null,
        payload: { parsed_name: "Dana Reyes", parsed_email: "dana@acme.invalid",
                   proposed_contact_type: "client",
                   new_contact_candidate: { first_name: "Dana", last_name: "Reyes" },
                   existing_candidates: [
                     { contact_id: "c1", name: "Dana Reyes", company: "Acme Facilities",
                       email: "dana@acme.invalid", match_reason: "email",
                       confidence: 0.98, rank: 1 }] } },
      // FR-5.9e — our own side of the table: recognised, not asked about.
      { id: "i0", kind: "participant", state: "approved", is_practice: true,
        source_excerpt: "Attendees: Bryan Baker, Dana Reyes",
        position: 0, created_record_type: "contact", created_record_id: "c9",
        actioned_at: null,
        payload: { parsed_name: "Bryan Baker", parsed_email: "bryan@x.test",
                   is_practice: true, practice_name: "Bryan Baker",
                   practice_role: "FF" } },
      { id: "i2", kind: "action_item", state: "pending",
        source_excerpt: "Dana said she would send the Q3 margin breakdown by Friday.",
        position: 0, created_record_type: "", created_record_id: null,
        actioned_at: null,
        payload: { text: "Send the Q3 margin breakdown",
                   proposed_due_date: "2026-09-25" } },
    ],
    ...overrides,
  };
}

function show(extra: Record<string, unknown> = {}, me = aMe()) {
  const fetchMock = mockApi({
    [`GET /api/meeting-proposals/${ID}/`]: aProposal(),
    "GET /api/meeting-proposals/": [aProposal()],
    // The more specific path first: mockApi matches on the first key the URL
    // starts with, so "/api/drive-watch/" would otherwise swallow this one.
    "GET /api/drive-watch/backfill/": { folder: PAST, backfill: null },
    "GET /api/drive-watch/": HEALTH,
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Meetings me={me} />, { path: "/meetings", route: "/meetings" });
  return fetchMock;
}

describe("the meeting queue", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows what is waiting and where the folder has got to", async () => {
    show();
    expect(await screen.findByText("Acme operations review")).toBeInTheDocument();
    expect(screen.getByText(/2 to review/)).toBeInTheDocument();
    expect(screen.getByText(/1 skipped/)).toBeInTheDocument();
  });

  it("shows every item with the passage it came from", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Review" }));

    // FR-5.14 — the claim is checkable, not merely assertable.
    expect(await screen.findByText(/“Dana said she would send the Q3 margin/))
      .toBeInTheDocument();
    expect(screen.getByText(/“Attendees: Dana Reyes/)).toBeInTheDocument();
    // And the match is explained, not just offered.
    expect(screen.getByRole("combobox", { name: "Match for Dana Reyes" }))
      .toHaveTextContent("matched on email");
  });

  it("always offers the create-new path beside the matches", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Review" }));
    const picker = screen.getByRole("combobox", { name: "Match for Dana Reyes" });
    expect(within(picker).getByRole("option", { name: /Someone new/ })).toBeInTheDocument();
  });

  it("approves one item on its own, carrying the confirmed type", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "POST /api/proposal-items/i1/approve/": { id: "i1" } });
    await user.click(await screen.findByRole("button", { name: "Review" }));

    await user.selectOptions(screen.getByRole("combobox", { name: "Type for Dana Reyes" }),
                             "coworker");
    await user.click(screen.getByRole("button", { name: "Approve Dana Reyes" }));

    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.url.endsWith("/i1/approve/"));
      expect(posted?.body).toMatchObject({ contact_type: "coworker" });
    });
  });

  it("asks what a vendor does before it will approve them", async () => {
    const user = userEvent.setup();
    show({ "POST /api/proposal-items/i1/approve/": { id: "i1" } });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    expect(screen.queryByLabelText(/Service categories/)).not.toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Type for Dana Reyes" }),
                             "vendor");
    expect(screen.getByLabelText("Service categories for Dana Reyes")).toBeInTheDocument();
  });

  it("lets the summary be edited or discarded before anything is approved", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ [`PATCH /api/meeting-proposals/${ID}/`]: aProposal() });
    await user.click(await screen.findByRole("button", { name: "Review" }));

    const box = await screen.findByLabelText("Meeting summary");
    expect(box).toHaveValue("Dispatch and margin reporting came up.");
    await user.clear(box);
    await user.type(box, "Two things were agreed.");
    await user.tab();
    await waitFor(() => {
      const patched = fetchMock.calls.find((c) => c.method === "PATCH");
      expect(patched?.body).toEqual({ summary: "Two things were agreed." });
    });

    await user.click(screen.getByRole("button", { name: /Discard the summary/ }));
    await waitFor(() => expect(fetchMock.calls.filter((c) => c.method === "PATCH").length)
      .toBeGreaterThan(1));
  });
});


/**
 * Connecting the folder (FR-5.1, FR-5.1a).
 *
 * The flow this covers is the one that was missing: an FF arriving at an empty
 * queue with no folder had no control that led anywhere. It has two steps that
 * fail separately — Drive access, then the folder — and the screen has to say
 * which of them is not done.
 */
describe("connecting the notes folder", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("sends the founder to Google when Drive access has not been granted", async () => {
    const user = userEvent.setup();
    const fetchMock = show({
      "GET /api/drive-watch/": { ...UNCONNECTED, drive_access: false },
      "POST /api/drive-watch/consent/": { authorization_url: "https://accounts.google.test/c" },
    });

    // Google's consent screen is a real navigation, so stand in for it and
    // assert the browser was actually sent there.
    const sentTo: string[] = [];
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { set href(url: string) { sentTo.push(url); } },
    });

    // Step 2 is visibly not yet available: the folder cannot be read before
    // the app may read the Drive at all.
    expect(await screen.findByLabelText("Drive folder link")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Allow Drive access/ }));

    await waitFor(() => expect(
      fetchMock.calls.some((c) => c.url.endsWith("/drive-watch/consent/"))).toBe(true));
    await waitFor(() => expect(sentTo).toEqual(["https://accounts.google.test/c"]));
  });

  it("points at Email settings when no Google account is connected at all", async () => {
    show({ "GET /api/drive-watch/": {
      ...UNCONNECTED, google_connected: false, drive_access: false, drive_account: "" } });

    expect(await screen.findByRole("link", { name: "Email settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Allow Drive access/ })).not.toBeInTheDocument();
  });

  it("checks a pasted Drive URL and saves nothing until it is confirmed", async () => {
    const user = userEvent.setup();
    const fetchMock = show({
      "GET /api/drive-watch/": UNCONNECTED,
      "POST /api/drive-watch/check/": { folder_id: "1AbC", name: "Gemini meeting notes",
                                        files: 14, readable: 12, truncated: false },
      "POST /api/drive-watch/": { ...HEALTH, folder_name: "Gemini meeting notes" },
    });

    await user.type(await screen.findByLabelText("Drive folder link"),
                    "https://drive.google.com/drive/folders/1AbC?usp=sharing");
    await user.click(screen.getByRole("button", { name: "Check folder" }));

    // What it is, before it is watched — including how much of it we can read,
    // which is the part a folder of PDFs would fail on.
    expect(await screen.findByText("Gemini meeting notes")).toBeInTheDocument();
    expect(screen.getByText(/14 files · 12 readable/)).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.method === "POST"
      && c.url.endsWith("/api/drive-watch/"))).toBe(false);

    // The whole pasted URL goes to the server: extracting the id is the
    // server's job, so a trailing ?usp=sharing cannot break it here.
    const checked = fetchMock.calls.find((c) => c.url.endsWith("/check/"));
    expect(checked?.body).toEqual({
      folder: "https://drive.google.com/drive/folders/1AbC?usp=sharing" });

    await user.click(screen.getByRole("button", { name: "Watch this folder" }));
    await waitFor(() => expect(screen.getByText(/Watching “Gemini meeting notes”/))
      .toBeInTheDocument());
  });

  it("says so when the folder holds nothing it can read", async () => {
    const user = userEvent.setup();
    show({
      "GET /api/drive-watch/": UNCONNECTED,
      "POST /api/drive-watch/check/": { folder_id: "1AbC", name: "Recordings",
                                        files: 9, readable: 0, truncated: false },
    });
    await user.type(await screen.findByLabelText("Drive folder link"), "1AbCdEfGhIj");
    await user.click(screen.getByRole("button", { name: "Check folder" }));

    expect(await screen.findByText(/Nothing in there can be read as notes/))
      .toBeInTheDocument();
  });

  it("surfaces the server's reason when the folder cannot be opened", async () => {
    const user = userEvent.setup();
    show({
      "GET /api/drive-watch/": UNCONNECTED,
      "POST /api/drive-watch/check/": () => ({
        status: 400, body: { detail: "That folder is in the Drive bin." } }),
    });
    await user.type(await screen.findByLabelText("Drive folder link"), "1AbCdEfGhIj");
    await user.click(screen.getByRole("button", { name: "Check folder" }));

    expect(await screen.findByText("That folder is in the Drive bin.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Watch this folder" })).not.toBeInTheDocument();
  });

  it("shows the watched folder, and disconnects it", async () => {
    const user = userEvent.setup();
    const fetchMock = show({
      "POST /api/drive-watch/disconnect/": { ...UNCONNECTED },
    });

    expect(await screen.findByText("Meeting notes")).toBeInTheDocument();
    expect(screen.getByText(/Watched folder/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Disconnect" }));

    await waitFor(() => expect(
      fetchMock.calls.some((c) => c.url.endsWith("/disconnect/"))).toBe(true));
    // And what it cost is stated: nothing already read is thrown away.
    expect(await screen.findByText(/reconnecting the same folder picks up/))
      .toBeInTheDocument();
  });

  it("gives a VA the folder's state and none of the controls", async () => {
    show({ "GET /api/drive-watch/": UNCONNECTED }, aMe({ role: "VA" }));

    // Matrix 11.10 — connecting is the founder's. Clearing the queue is not.
    expect(await screen.findByText(/The practice owner connects it/))
      .toBeInTheDocument();
    expect(screen.queryByLabelText("Drive folder link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Allow Drive access/ }))
      .not.toBeInTheDocument();
  });

  it("reports the outcome Google redirected back with", async () => {
    const fetchMock = mockApi({
      "GET /api/meeting-proposals/": [],
      "GET /api/drive-watch/": { ...UNCONNECTED, drive_access: false },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Meetings me={aMe()} />, {
      path: "/meetings",
      route: "/meetings?drive_error=Consent was granted without Drive access.",
    });

    expect(await screen.findByText(/Consent was granted without Drive access/))
      .toBeInTheDocument();
  });
});


/**
 * The folder's past (FR-5.1b).
 *
 * Diagnosed on the owner's real folder: "Sync now" reported 0 waiting on 167
 * readable notes, because Drive's change cursor starts at "now". Reading the
 * past is a separate decision with a price on it, and this panel is where it
 * is made.
 */
describe("importing what the folder already holds", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says what is there and that watching alone will not find it", async () => {
    show();

    expect(await screen.findByText(/167 readable notes/)).toBeInTheDocument();
    // The thing that is not obvious, said plainly — including that "Sync now"
    // is not the control that will fetch them.
    expect(screen.getByText(/“Sync now” will not find these/)).toBeInTheDocument();
    expect(screen.getByText(/from 2026-03-30 to 2026-09-11/)).toBeInTheDocument();
  });

  it("shows the count and the estimated cost before anything is confirmed", async () => {
    const fetchMock = show();

    expect(await screen.findByText(/\$9\.60/)).toBeInTheDocument();
    expect(screen.getByText(/about \$0\.0575 each, estimated/)).toBeInTheDocument();
    expect(screen.getByText(/roughly 56 minutes/)).toBeInTheDocument();
    // Nothing has started.
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("offers all three, and records starting from now as an answer", async () => {
    const user = userEvent.setup();
    const fetchMock = show({
      "POST /api/drive-watch/backfill/": aBackfill({ state: "declined", running: false }),
    });

    await user.click(await screen.findByRole("radio", { name: /only new notes/ }));
    // No cost line for the option that reads nothing.
    expect(screen.queryByText(/of AI/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start from now" }));

    await waitFor(() => {
      const posted = fetchMock.calls.find(
        (c) => c.method === "POST" && c.url.endsWith("/backfill/"));
      expect(posted?.body).toEqual({ scope: "now", since: null });
    });
  });

  it("re-counts and re-prices when the date changes, before confirming", async () => {
    const user = userEvent.setup();
    const fetchMock = show({
      "POST /api/drive-watch/backfill/plan/": { since: "2026-07-01", outstanding: 24,
                                                per_note_usd: "0.0575",
                                                per_note_is_measured: false,
                                                estimate_usd: "1.38", minutes: 8 },
      "POST /api/drive-watch/backfill/": aBackfill({ scope: "since" }),
    });

    // `fireEvent.change` rather than typing: a date input takes its value as a
    // whole, not a keystroke at a time.
    fireEvent.change(await screen.findByLabelText("Import notes since"),
                     { target: { value: "2026-07-01" } });

    // The whole sentence, because the count, the price and the time are one
    // statement and it is the statement that is being agreed to.
    const priced = await screen.findByText(/of AI/);
    expect(priced).toHaveTextContent("24 notes");
    expect(priced).toHaveTextContent("$1.38");
    expect(priced).toHaveTextContent("roughly 8 minutes");
    await user.click(screen.getByRole("button", { name: /Import 24 notes/ }));

    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.method === "POST"
        && c.url.endsWith("/api/drive-watch/backfill/"));
      expect(posted?.body).toEqual({ scope: "since", since: "2026-07-01" });
    });
  });

  it("shows progress and the spend as it goes, with a way to stop", async () => {
    const user = userEvent.setup();
    const fetchMock = show({
      "GET /api/drive-watch/": { ...HEALTH, backfill: aBackfill() },
      "POST /api/drive-watch/backfill/stop/": aBackfill({ state: "cancelled",
                                                          running: false }),
    });

    // The spend is visible while it runs — that is the reason for pacing.
    expect(await screen.findByText(/42 read of 167/)).toBeInTheDocument();
    expect(screen.getByText(/\$2\.4100 spent so far/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Import progress" }))
      .toHaveAttribute("aria-valuenow", "26");

    await user.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(
      fetchMock.calls.some((c) => c.url.endsWith("/backfill/stop/"))).toBe(true));
  });

  it("keeps offering while older notes remain unread", async () => {
    /* The finding: an import that read 8 of 167 left 159 unread, and the panel
       congratulated itself and disappeared. */
    show({
      "GET /api/drive-watch/": { ...HEALTH,
        backfill: aBackfill({ state: "done", running: false, done: 8,
                              planned: 8, cost_usd: "0.460000" }) },
      // The folder's own last import comes with its survey (2026-09-28): with
      // more than one folder, the latest import may be another folder's.
      "GET /api/drive-watch/backfill/": {
        folder: { ...PAST, outstanding: 159, estimate_usd: "9.14", minutes: 53 },
        backfill: aBackfill({ state: "done", running: false, done: 8,
                              planned: 8, cost_usd: "0.460000" }) },
    });

    expect(await screen.findByText("Older notes in Meet Recordings are still unread"))
      .toBeInTheDocument();
    expect(screen.getByText(/159 readable notes/)).toBeInTheDocument();
    expect(screen.getByText(/You imported 8 last time/)).toBeInTheDocument();
    // The same three choices, and the third one counts what is left, not the
    // original total.
    expect(screen.getByRole("radio", { name: /only new notes/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /since/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Import the remaining 159/ }))
      .toBeInTheDocument();
    expect(screen.getByText(/\$9\.14/)).toBeInTheDocument();
  });

  it("says on the folder card what is not being read", async () => {
    show({
      "GET /api/drive-watch/": { ...HEALTH,
        backfill: aBackfill({ state: "done", running: false, done: 8 }) },
      "GET /api/drive-watch/backfill/": {
        folder: { ...PAST, outstanding: 159 }, backfill: null },
    });

    // On the card that says the folder is being watched, because that is the
    // card somebody reads when they wonder why nothing is arriving.
    expect(await screen.findByText(/159 older notes not imported/))
      .toBeInTheDocument();
    expect(screen.getByText(/Watching for new notes/)).toBeInTheDocument();
  });

  it("goes quiet only when nothing is left unread", async () => {
    show({
      "GET /api/drive-watch/": { ...HEALTH,
        backfill: aBackfill({ state: "done", running: false, done: 167 }) },
      "GET /api/drive-watch/backfill/": {
        folder: { ...PAST, outstanding: 0 },
        backfill: aBackfill({ state: "done", running: false, done: 167 }) },
    });

    expect(await screen.findByText(/Nothing older is left unread/)).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /only new notes/ }))
      .not.toBeInTheDocument();
  });

  it("names the subfolders when that is where the notes live", async () => {
    show({ "GET /api/drive-watch/backfill/": {
      folder: { ...PAST, readable_here: 0, readable_in_subfolders: 167,
                subfolders: [{ name: "Acme", readable: 120 },
                             { name: "Northwind", readable: 47 }] },
      backfill: null } });

    expect(await screen.findByText(/Including 167 in Acme, Northwind/))
      .toBeInTheDocument();
    expect(screen.getByText(/subfolders are read too, one level down/))
      .toBeInTheDocument();
  });

  it("is the founder's, like the folder itself", async () => {
    show({ "GET /api/drive-watch/": HEALTH }, aMe({ role: "VA" }));

    expect(await screen.findByText("Meeting notes")).toBeInTheDocument();
    expect(screen.queryByText(/already holds notes/)).not.toBeInTheDocument();
  });
});


describe("our own side of the table", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the practice as attending and asks nothing about them", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Review" }));

    // Shown — who was in the room is the point of the record.
    expect(await screen.findByText(/Bryan Baker · bryan@x.test/)).toBeInTheDocument();
    expect(screen.getByText(/— your practice\. Recorded as attending/))
      .toBeInTheDocument();

    // Not asked about: no type, no match picker, no approve, no reject.
    expect(screen.queryByRole("combobox", { name: "Type for Bryan Baker" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Match for Bryan Baker" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve Bryan Baker" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject Bryan Baker" }))
      .not.toBeInTheDocument();

    // And the real participant is still a question.
    expect(screen.getByRole("combobox", { name: "Type for Dana Reyes" }))
      .toBeInTheDocument();
  });
});


/**
 * 2026-09-28 — Google Meet watched at any depth, and titles that are never
 * read. The folder card shows what each folder kept out.
 */
describe("more than one folder, and what is never read", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const MEET = { id: "wf1", folder_id: "gmeet", folder_name: "Google Meet", depth: "any",
                 name_pattern: "Notes by Gemini", files_recorded: 6, excluded: 1 };
  const EXCLUSIONS = [{ id: "x1", pattern: "AoA", source: "seed" },
                      { id: "x2", pattern: "Academy of America", source: "seed" }];
  const WITH_MEET = { ...HEALTH, excluded: 0, folders: [MEET], exclusions: EXCLUSIONS };

  it("shows each folder with its depth, pattern and excluded count", async () => {
    show({ "GET /api/drive-watch/": WITH_MEET });

    const card = (await screen.findByRole("heading", { name: "Google Meet" }))
      .closest("section")!;
    expect(card).toHaveTextContent("every folder inside it");
    expect(card).toHaveTextContent("only Google Docs named like “Notes by Gemini”");
    expect(card).toHaveTextContent("1 excluded");
  });

  it("lists what is never read, and the founder can add to it", async () => {
    const user = userEvent.setup();
    const fetchMock = show({
      "GET /api/drive-watch/": WITH_MEET,
      "POST /api/drive-watch/exclusions/": { ...WITH_MEET,
        exclusions: [...EXCLUSIONS, { id: "x3", pattern: "Board dinner", source: "manual" }] },
    }, aMe({ role: "FF" }));

    expect(await screen.findByText("AoA")).toBeInTheDocument();
    expect(screen.getByText("Academy of America")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Exclude titles containing"), "Board dinner");
    await user.click(screen.getByRole("button", { name: "Exclude" }));

    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ pattern: "Board dinner" }));
    expect(await screen.findByText("Board dinner")).toBeInTheDocument();
  });

  it("shows the list but no controls to anyone but the founder", async () => {
    show({ "GET /api/drive-watch/": WITH_MEET }, aMe({ role: "VA" }));

    expect(await screen.findByText("AoA")).toBeInTheDocument();
    expect(screen.queryByLabelText("Exclude titles containing")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Read AoA again/ })).not.toBeInTheDocument();
  });

  it("Ignore this file starts from the meeting's name and sends what was confirmed",
    async () => {
      const user = userEvent.setup();
      const proposal = aProposal({ source_file: { ...aProposal().source_file,
        name: "AoA Planning Session - 2026/09/24 17:35 MDT - Notes by Gemini" } });
      const fetchMock = show({
        [`GET /api/meeting-proposals/${ID}/`]: proposal,
        "GET /api/meeting-proposals/": [proposal],
        [`POST /api/meeting-proposals/${ID}/ignore/`]: proposal,
      }, aMe({ role: "FF" }));

      await user.click(await screen.findByRole("button", { name: "Review" }));
      await user.click(await screen.findByRole("button", { name: /Ignore this file/ }));
      const pattern = screen.getByLabelText(/Never read meetings whose title/);
      expect(pattern).toHaveValue("AoA Planning Session");
      await user.clear(pattern);
      await user.type(pattern, "AoA");
      await user.click(screen.getByRole("button", { name: "Ignore" }));

      await waitFor(() => expect(fetchMock.calls.find((c) =>
        c.url.endsWith("/ignore/"))?.body).toEqual({ pattern: "AoA" }));
    });

  it("offers Ignore this file only to the founder", async () => {
    const user = userEvent.setup();
    show({}, aMe({ role: "VA" }));

    await user.click(await screen.findByRole("button", { name: "Review" }));
    await screen.findByLabelText("Meeting summary");
    expect(screen.queryByRole("button", { name: /Ignore this file/ })).not.toBeInTheDocument();
  });
});

describe("meetingNameOf", () => {
  it("takes the meeting's own name from a Gemini file name", async () => {
    const { meetingNameOf } = await import("./Meetings");
    expect(meetingNameOf(
      "30 Minutes w/ Bryan Baker (Rick Turner) - 2026/09/28 10:59 MDT - Notes by Gemini"))
      .toBe("30 Minutes w/ Bryan Baker (Rick Turner)");
    expect(meetingNameOf("Board dinner - Notes by Gemini")).toBe("Board dinner");
    expect(meetingNameOf("Plain notes")).toBe("Plain notes");
  });
});


/** 2026-09-28 — Dismiss: a reason, nothing created, and a way back. */
describe("dismissing a proposal", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const sent = (fetchMock: ReturnType<typeof mockApi>, end: string) =>
    fetchMock.calls.find((c) => c.method === "POST" && c.url.endsWith(end))?.body;

  async function openDismiss(extra: Record<string, unknown> = {}) {
    const user = userEvent.setup();
    const fetchMock = show({
      [`POST /api/meeting-proposals/${ID}/dismiss/`]: aProposal({ state: "dismissed" }),
      ...extra,
    });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    await user.click(await screen.findByRole("button", { name: /^Dismiss$/ }));
    return { user, fetchMock };
  }

  it("sends the reason and the note", async () => {
    const { user, fetchMock } = await openDismiss();
    await user.click(screen.getByRole("radio", { name: "No meeting happened" }));
    await user.type(screen.getByLabelText("Dismissal note"), "Calendar hold only.");
    await user.click(screen.getByRole("button", { name: /^Dismiss$/ }));

    await waitFor(() => expect(sent(fetchMock, "/dismiss/"))
      .toEqual({ reason: "no_meeting", note: "Calendar hold only." }));
  });

  it("will not dismiss as Other without saying why", async () => {
    const { user } = await openDismiss();
    await user.click(screen.getByRole("radio", { name: "Other" }));
    const dismiss = screen.getByRole("button", { name: /^Dismiss$/ });
    expect(dismiss).toBeDisabled();
    await user.type(screen.getByLabelText("Dismissal note"), "Personal call.");
    expect(dismiss).toBeEnabled();
  });

  it("records the vendor with what they do and dismisses the rest", async () => {
    const { user, fetchMock } = await openDismiss();
    await user.click(screen.getByRole("radio", { name: "Vendor pitch" }));
    const record = screen.getByRole("button", { name: "Record as vendor and dismiss the rest" });
    expect(record).toBeDisabled();                       // needs a category first
    await user.type(screen.getByLabelText("Vendor service categories"),
                    "Duct cleaning, grease traps");
    await user.click(record);

    await waitFor(() => expect(sent(fetchMock, "/dismiss/")).toEqual({
      reason: "vendor_pitch", note: "",
      vendor: { item: "i1", service_categories: ["Duct cleaning", "grease traps"] },
    }));
  });

  it("lists what was dismissed under Archived, with why, and restores it", async () => {
    const user = userEvent.setup();
    const dismissed = aProposal({ state: "dismissed", dismissed: {
      reason: "vendor_pitch", reason_label: "Vendor pitch", note: "Recorded Tom as a vendor.",
      by: "Bryan Baker", at: "2026-09-28T19:00:00Z" } });
    // Its own routes, in order: the archived list must be matched before the
    // open one its address starts with.
    const fetchMock = mockApi({
      "GET /api/meeting-proposals/?state=archived": [dismissed],
      [`POST /api/meeting-proposals/${ID}/restore/`]: aProposal(),
      "GET /api/meeting-proposals/": [],
      "GET /api/drive-watch/backfill/": { folder: PAST, backfill: null },
      "GET /api/drive-watch/": HEALTH,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Meetings me={aMe()} />, { path: "/meetings", route: "/meetings" });

    await user.click(await screen.findByRole("button", { name: "Archived" }));
    expect(await screen.findByText("Vendor pitch")).toBeInTheDocument();
    expect(screen.getByText(/Recorded Tom as a vendor/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => expect(fetchMock.calls.some((c) =>
      c.method === "POST" && c.url.endsWith("/restore/"))).toBe(true));
  });
});


describe("a panel whose notes another folder offers too", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says how many are shared and how many are already recorded", async () => {
    show({ "GET /api/drive-watch/backfill/": { backfill: null, folder: {
      ...PAST, outstanding: 127, already_recorded: 2,
      shared_with: [{ folder: "wf1", folder_name: "Google Meet", count: 116 }] } } });

    expect(await screen.findByText(
      /116 of these are the same notes the Google Meet panel offers/)).toBeInTheDocument();
    expect(screen.getByText(/Import either one; the other then finds them already read/))
      .toBeInTheDocument();
    expect(screen.getByText(/2 more are meetings already recorded from another folder/))
      .toBeInTheDocument();
  });
});


describe("an import past the estimated AI balance", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("asks, and imports anyway only when told to", async () => {
    const user = userEvent.setup();
    let calls = 0;
    const fetchMock = show({ "POST /api/drive-watch/backfill/": (body: unknown) =>
      (calls++ === 0 && !(body as { confirm_over_balance?: boolean }).confirm_over_balance)
        ? { status: 409, body: { needs_confirmation: true, estimated_balance: "1.00",
            estimated_cost: "9.63", detail: "This import should cost about $9.63, more "
              + "than the estimated $1.00 left on the Anthropic account. Import anyway?" } }
        : { status: 201, body: {} } }, aMe({ role: "FF" }));

    await user.click(await screen.findByRole("button", { name: /^Import/ }));
    expect(await screen.findByText(/more than the estimated \$1\.00 left/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Import anyway" }));

    await waitFor(() => expect(fetchMock.calls
      .filter((c) => c.method === "POST" && c.url.endsWith("/backfill/"))
      .map((c) => (c.body as { confirm_over_balance?: boolean }).confirm_over_balance))
      .toEqual([undefined, true]));
  });
});


/** 2026-09-28 — whose action item it is, and what approving it does. */
describe("an action item owned by someone else", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const withOwner = (payload: Record<string, unknown>, name = "Dana Reyes") => {
    const base = aProposal();
    const items = (base.items ?? []).map((i) => i.id === "i2" ? {
      ...i, owner_contact_name: name,
      payload: { ...i.payload, proposed_owner_text: name, proposed_owner_contact_id: "c1",
                 owner_side: "other", ...payload } } : i);
    return aProposal({ items: items as never });
  };

  async function open(proposal: ReturnType<typeof aProposal>) {
    const user = userEvent.setup();
    const fetchMock = show({
      [`GET /api/meeting-proposals/${ID}/`]: proposal,
      "POST /api/proposal-items/i2/approve/": {},
    });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    return { user, fetchMock };
  }

  it("proposes the portal for a client user with a seat and sends that choice", async () => {
    const { user, fetchMock } = await open(withOwner({
      owner_kind: "client", owner_has_seat: true, proposed_outcome: "portal" }));
    expect(await screen.findByText(/Dana Reyes — client · has a portal seat/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Assign in the portal/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: /Approve Send the Q3/ }));

    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/i2/approve/"))
      ?.body).toEqual({ owner_side: "other", owner_kind: "client", outcome: "portal",
                        notify_me: true }));
  });

  it("cannot assign in the portal without a seat, and follows up by default", async () => {
    const { user, fetchMock } = await open(withOwner({
      owner_kind: "prospect", owner_has_seat: false, proposed_outcome: "follow_up" }));
    expect(await screen.findByRole("radio", { name: /Assign in the portal/ })).toBeDisabled();
    expect(screen.getByLabelText("Follow-up date")).toHaveValue("2026-09-25");
    await user.click(screen.getByRole("button", { name: /Approve Send the Q3/ }));

    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/i2/approve/"))
      ?.body).toEqual({ owner_side: "other", owner_kind: "prospect", outcome: "follow_up",
                        follow_up_date: "2026-09-25" }));
  });

  it("records only when chosen", async () => {
    const { user, fetchMock } = await open(withOwner({
      owner_kind: "vendor", proposed_outcome: "record_only" }));
    await user.click(await screen.findByRole("radio", { name: /Record only/ }));
    await user.click(screen.getByRole("button", { name: /Approve Send the Q3/ }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/i2/approve/"))
      ?.body).toMatchObject({ owner_side: "other", outcome: "record_only" }));
  });

  it("names the practice where it used to say ours and us", async () => {
    const user = userEvent.setup();
    show({ [`GET /api/meeting-proposals/${ID}/`]: withOwner({ owner_kind: "prospect" }),
           "GET /api/branding": { display_name: "Summit Operations Partners" } });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByRole("radio",
      { name: "Summit Operations Partners' — make it a task" })).toBeInTheDocument();
    expect(screen.getByText(/a task for Summit Operations Partners to check it happened/))
      .toBeInTheDocument();
    expect(screen.getByLabelText("What Dana Reyes is to Summit Operations Partners"))
      .toBeInTheDocument();
    expect(screen.queryByText(/\bOurs\b/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bfor us\b/)).not.toBeInTheDocument();
  });

  const PEOPLE = [
    { id: "u1", name: "Bryan Baker", role: "FF", company: null },
    { id: "u2", name: "Val the Assistant", role: "VA", company: null },
    { id: "u3", name: "Dana Reyes", role: "FCC", company: "co1" },
    { id: "u4", name: "Lee Marsh", role: "ECC", company: "co1" },
    { id: "u5", name: "Someone at Ridgeline", role: "FCC", company: "co2" },
  ];
  const SEAT = { user_id: "u3", company_id: "co1", company_name: "Acme" };
  const seated = () => {
    const base = withOwner({ owner_kind: "client", owner_has_seat: false,
                             proposed_outcome: "record_only" });
    return aProposal({ items: (base.items ?? []).map((i) => i.id === "i2"
      ? { ...i, owner_seat: SEAT } : i) as never });
  };
  const WORK = {
    "GET /api/portal-people/": PEOPLE,
    "GET /api/goals/": [{ id: "g1", title: "Cut overload", is_historical: false },
                        { id: "g9", title: "Last year's", is_historical: true }],
    "GET /api/projects/": [{ id: "p1", title: "Order to cash", goal: "g1" },
                           { id: "p2", title: "Loose project", goal: null }],
    "GET /api/tasks/": [
      { id: "t1", title: "Map the invoice process", project: "p1", goal: null,
        is_client_visible: true, status: "in_progress" },
      { id: "t2", title: "Hidden from the client", project: "p1", goal: null,
        is_client_visible: false, status: "in_progress" },
      { id: "t3", title: "In the loose project", project: "p2", goal: null,
        is_client_visible: true, status: "not_started" }],
  };

  it("offers the portal by the seat as it is now, not as it was when the notes were read",
    async () => {
      const { user, fetchMock } = await open(seated());
      // The notes said no seat; they have one now.
      const portal = await screen.findByRole("radio", { name: /Assign in the portal/ });
      expect(portal).toBeEnabled();
      await user.click(portal);
      expect(await screen.findByRole("group", { name: "File it for Acme" }))
        .toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /Approve Send the Q3/ }));
      // Nothing chosen in the tool: what it sent before, and nothing more.
      await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/i2/approve/"))
        ?.body).toEqual({ owner_side: "other", owner_kind: "client", outcome: "portal",
                          notify_me: true }));
    });

  it("files the client's task: goal, then project, then task, or a new one at any level",
    async () => {
      const user = userEvent.setup();
      const fetchMock = show({ [`GET /api/meeting-proposals/${ID}/`]: seated(), ...WORK,
                               "POST /api/proposal-items/i2/approve/": {} });
      await user.click(await screen.findByRole("button", { name: "Review" }));
      await user.click(await screen.findByRole("radio", { name: /Assign in the portal/ }));
      const tool = await screen.findByRole("group", { name: "File it for Acme" });

      // Only this client's own people, and the person named by default.
      const who = within(tool).getByLabelText("Assign the client's task to");
      await within(who).findByRole("option", { name: "Lee Marsh" });
      expect(within(who).getAllByRole("option").map((o) => o.textContent))
        .toEqual(["Dana Reyes", "Lee Marsh"]);
      expect(who).toHaveValue("u3");

      // An existing goal narrows the projects to its own; a historical goal is not offered.
      const goal = within(tool).getByLabelText("Under which goal");
      expect(within(goal).queryByRole("option", { name: "Last year's" })).toBeNull();
      await user.selectOptions(goal, "g1");
      const project = within(tool).getByLabelText("In which project");
      expect(within(project).getAllByRole("option").map((o) => o.textContent))
        .toEqual(["No project", "Order to cash", "A new project…"]);
      await user.selectOptions(project, "p1");
      // Only tasks of that project that the client can see.
      const task = within(tool).getByLabelText("Which task");
      expect(within(task).getAllByRole("option").map((o) => o.textContent))
        .toEqual(["A new task, from this item", "Map the invoice process"]);

      // A new project in place, under the existing goal, for a colleague.
      await user.selectOptions(project, "new");
      await user.type(within(tool).getByLabelText("The new project"), "Month-end checklist");
      await user.selectOptions(who, "u4");
      await user.click(screen.getByRole("button", { name: /Approve Send the Q3/ }));
      await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/i2/approve/"))
        ?.body).toEqual({
          owner_side: "other", owner_kind: "client", outcome: "portal", notify_me: true,
          assignee_id: "u4",
          file: { goal: "g1", project: "new", project_title: "Month-end checklist" } }));
    });

  it("assigns a practice task to anyone on the team", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ [`GET /api/meeting-proposals/${ID}/`]: withOwner({
                               owner_kind: "client" }), ...WORK,
                             "POST /api/proposal-items/i2/approve/": {} });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    await user.click(await screen.findByRole("radio", { name: /— make it a task/ }));
    const who = screen.getByLabelText("Assign the task to");
    await within(who).findByRole("option", { name: "Val the Assistant" });
    // The team only: no client user is offered a practice task.
    expect(within(who).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["Assigned to nobody yet", "Bryan Baker", "Val the Assistant"]);
    await user.selectOptions(who, "u2");
    await user.click(screen.getByRole("button", { name: /Approve Send the Q3/ }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/i2/approve/"))
      ?.body).toEqual({ owner_side: "practice", promised: false, assignee_id: "u2" }));
  });

  it("lets the reviewer say it is ours after all", async () => {
    const { user, fetchMock } = await open(withOwner({ owner_kind: "client" }));
    await user.click(await screen.findByRole("radio", { name: /— make it a task/ }));
    await user.click(screen.getByRole("button", { name: /Approve Send the Q3/ }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/i2/approve/"))
      ?.body).toEqual({ owner_side: "practice", promised: false }));
  });
});

describe("a promise is a mark on a task (2026-10-20)", () => {
  const promised = (extra: Record<string, unknown> = {}) => {
    const base = aProposal();
    const items = (base.items ?? []).map((i) => i.id === "i2" ? {
      ...i, promised_to: { id: "co1", name: "Acme Facilities" },
      payload: { ...i.payload, owner_side: "practice", promised_to_client: true, ...extra } }
      : i);
    return aProposal({ items: items as never });
  };

  it("pre-ticks “Promised to <company>” when Claude read a promise, and sends it", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ [`GET /api/meeting-proposals/${ID}/`]: promised(),
                             "POST /api/proposal-items/i2/approve/": {} });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    const tick = await screen.findByRole("checkbox", { name: "Promised to Acme Facilities" });
    expect(tick).toBeChecked();
    await user.click(screen.getByRole("button", { name: /Approve Send the Q3/ }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/i2/approve/"))
      ?.body).toEqual({ owner_side: "practice", promised: true }));
  });

  it("can be unticked", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ [`GET /api/meeting-proposals/${ID}/`]: promised(),
                             "POST /api/proposal-items/i2/approve/": {} });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    await user.click(await screen.findByRole("checkbox", { name: "Promised to Acme Facilities" }));
    await user.click(screen.getByRole("button", { name: /Approve Send the Q3/ }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/i2/approve/"))
      ?.body).toEqual({ owner_side: "practice", promised: false }));
  });
});

describe("creating someone new over a strong email match (owner, 2026-09-29)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const MATCH = { contact_id: "c1", name: "Dana Reyes", email: "dana@acme.invalid",
                  company: "Acme Facilities", match_reason: "email", confidence: 0.98 };

  function refusingOnce() {
    let first = true;
    return (body: unknown) => {
      const sent = body as Record<string, unknown>;
      if (first && !sent.contact_id && !sent.create_despite_match) {
        first = false;
        return { status: 409, body: {
          detail: "Dana Reyes (dana@acme.invalid) is already a contact, matched on email "
                  + "address. Link to them, or confirm that this is a different person.",
          match: MATCH } };
      }
      return { status: 201, body: { id: "i1" } };
    };
  }

  it("names the match and sends the declined contact's id to create anyway", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "POST /api/proposal-items/i1/approve/": refusingOnce() });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    // The match is the default now; the reviewer chooses "Someone new".
    await user.selectOptions(screen.getByRole("combobox", { name: "Match for Dana Reyes" }), "");
    await user.click(screen.getByRole("button", { name: "Approve Dana Reyes" }));

    expect(await screen.findByText(/is already a contact/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Link to Dana Reyes" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "No, create a new contact anyway" }));

    await waitFor(() => {
      const posts = fetchMock.calls.filter((c) => c.url.endsWith("/i1/approve/"));
      expect(posts).toHaveLength(2);
      expect(posts[1].body).toMatchObject({ create_despite_match: "c1" });
    });
  });

  it("links to the match instead, in one click", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "POST /api/proposal-items/i1/approve/": refusingOnce() });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    // The match is the default now; the reviewer chooses "Someone new".
    await user.selectOptions(screen.getByRole("combobox", { name: "Match for Dana Reyes" }), "");
    await user.click(screen.getByRole("button", { name: "Approve Dana Reyes" }));
    await user.click(await screen.findByRole("button", { name: "Link to Dana Reyes" }));

    await waitFor(() => {
      const posts = fetchMock.calls.filter((c) => c.url.endsWith("/i1/approve/"));
      expect(posts[1].body).toMatchObject({ contact_id: "c1" });
      expect(posts[1].body).not.toHaveProperty("create_despite_match");
    });
  });
});

describe("notes that could not be read (owner, 2026-09-29)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const FAILED = [
    { id: "f9", name: "Meeting started 2026/05/15 10:59 MDT - Notes by Gemini",
      error: "Claude's answer was cut off or empty; nothing was kept. Failed 2 times "
             + "automatically; not tried again until someone chooses Read again.",
      web_view_link: "https://d/f9", automatic_failures: 2, retries_automatically: false,
      state: "failed", mime_type: "", skip_reason: "", owner_email: "", fetched_at: null },
    { id: "f8", name: "Weekly sync", error: "Queued to be read again (1 of 2).",
      web_view_link: "", automatic_failures: 1, retries_automatically: true,
      state: "failed", mime_type: "", skip_reason: "", owner_email: "", fetched_at: null },
  ];

  it("names each one, and offers Read again only once the automatic tries are spent",
    async () => {
      const user = userEvent.setup();
      // Built here rather than through show(): mockApi takes the first key a
      // URL starts with, so the specific drive-watch routes must come first.
      const fetchMock = mockApi({
        "GET /api/drive-watch/failed/": FAILED,
        "POST /api/drive-watch/read-again/": { ...FAILED[0], retries_automatically: true },
        "GET /api/drive-watch/backfill/": { folder: PAST, backfill: null },
        "GET /api/drive-watch/": { ...HEALTH, files_failed: 2, files_needing_person: 1 },
        [`GET /api/meeting-proposals/${ID}/`]: aProposal(),
        "GET /api/meeting-proposals/": [aProposal()],
      });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<Meetings me={aMe()} />, { path: "/meetings", route: "/meetings" });
      expect(await screen.findByText(/Meeting started 2026\/05\/15/)).toBeInTheDocument();
      expect(screen.getByText("Retrying (1 of 2)")).toBeInTheDocument();
      const buttons = screen.getAllByRole("button", { name: /Read again/ });
      expect(buttons).toHaveLength(1);
      await user.click(buttons[0]);
      await waitFor(() => {
        const post = fetchMock.calls.find((c) => c.url.endsWith("/read-again/"));
        expect(post?.body).toEqual({ file: "f9" });
      });
    });
});

describe("choosing who a participant or an owner is (owner, 2026-09-29)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const RICHARDS = [
    { contact_id: "r1", name: "Richard Hein", company: "Hein Plumbing", email: "rich@hein.test",
      emails: ["rich@hein.test"], last_meeting: "2026-09-10", match_reason: "name_only",
      confidence: 0.4, rank: 1 },
    { contact_id: "r2", name: "Richard Hein", company: "", email: "",
      emails: [], last_meeting: null, match_reason: "name_only", confidence: 0.4, rank: 2 },
  ];

  function withItems(items: MeetingProposal["items"]) {
    return show({ [`GET /api/meeting-proposals/${ID}/`]: aProposal({ items }) });
  }

  it("defaults to a strong match, with Someone new second", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Review" }));
    const picker = screen.getByRole("combobox", { name: "Match for Dana Reyes" }) as HTMLSelectElement;
    expect(picker.value).toBe("c1");
    const options = within(picker).getAllByRole("option").map((o) => o.textContent);
    expect(options[0]).toMatch(/^Dana Reyes · Acme Facilities/);
    expect(options[1]).toMatch(/Someone new/);
  });

  it("lists every same-named contact with what tells them apart, defaulting to new",
    async () => {
      const user = userEvent.setup();
      withItems([{ id: "i1", kind: "participant", state: "pending", source_excerpt: "Richard Hein",
        position: 0, created_record_type: "", created_record_id: null, actioned_at: null,
        candidates: RICHARDS,
        payload: { parsed_name: "Richard Hein", proposed_contact_type: "client",
                   existing_candidates: [] } }]);
      await user.click(await screen.findByRole("button", { name: "Review" }));
      const picker = screen.getByRole("combobox", { name: "Match for Richard Hein" }) as HTMLSelectElement;
      expect(picker.value).toBe("");
      const options = within(picker).getAllByRole("option").map((o) => o.textContent);
      expect(options).toEqual([
        "Someone new — create them",
        "Richard Hein · Hein Plumbing · rich@hein.test · last met 2026-09-10 — matched on name only",
        "Richard Hein · no meetings — matched on name only",
      ]);
      expect(screen.getByText(/2 contacts are called Richard Hein/)).toBeInTheDocument();
    });

  it("asks which one an ambiguous owner is, and sends the choice", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      [`GET /api/meeting-proposals/${ID}/`]: aProposal({ items: [{
        id: "a1", kind: "action_item", state: "pending", source_excerpt: "Richard will send it.",
        position: 0, created_record_type: "", created_record_id: null, actioned_at: null,
        owner_candidates: RICHARDS,
        payload: { text: "Send the quote", proposed_owner_text: "Richard Hein",
                   owner_side: "other", owner_kind: "client", proposed_outcome: "record_only" } }] }),
      "GET /api/meeting-proposals/": [aProposal()],
      "GET /api/drive-watch/backfill/": { folder: PAST, backfill: null },
      "GET /api/drive-watch/": HEALTH,
      "POST /api/proposal-items/a1/approve/": { status: 201, body: { id: "a1" } },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Meetings me={aMe()} />, { path: "/meetings", route: "/meetings" });
    await user.click(await screen.findByRole("button", { name: "Review" }));
    const which = screen.getByRole("combobox", { name: "Which Richard Hein" }) as HTMLSelectElement;
    // No strong match: nobody is chosen for the reviewer.
    expect(which.value).toBe("");
    await user.selectOptions(which, "r1");
    await user.click(screen.getByRole("button", { name: "Approve Send the quote" }));
    await waitFor(() => {
      const post = fetchMock.calls.find((c) => c.url.endsWith("/a1/approve/"));
      expect(post?.body).toMatchObject({ owner_side: "other", owner_contact_id: "r1" });
    });
  });
});

/**
 * OneDrive, for a practice on Microsoft 365 (2026-10-27): the same two steps,
 * with the folder chosen by browsing.
 */
describe("the notes folder on OneDrive", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const ROOT = { id: "01ROOT", name: "OneDrive", is_root: true, path: [], parent_id: "",
                 folders: [{ id: "01DOCS", name: "Documents", items: 4 },
                           { id: "01MEET", name: "Meetings", items: 5 }],
                 files: 1, readable: 0 };
  const MEET = { id: "01MEET", name: "Meetings", is_root: false, path: ["Meetings"],
                 parent_id: "01ROOT", folders: [{ id: "01CLI", name: "Clients", items: 1 }],
                 files: 3, readable: 2 };

  function onOneDrive(health: Record<string, unknown>, extra: Record<string, unknown> = {}) {
    // The most specific paths first: mockApi takes the first key a URL starts with.
    const fetchMock = mockApi({
      "GET /api/drive-watch/onedrive-folders/?folder=01MEET": MEET,
      "GET /api/drive-watch/onedrive-folders/": ROOT,
      "GET /api/drive-watch/backfill/": { folder: PAST, backfill: null },
      "GET /api/drive-watch/": { ...UNCONNECTED, provider: "microsoft", ...health },
      "GET /api/meeting-proposals/": [],
      ...extra,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Meetings me={aMe()} />, { path: "/meetings", route: "/meetings" });
    return fetchMock;
  }

  it("asks Microsoft for OneDrive access first", async () => {
    const user = userEvent.setup();
    const sentTo: string[] = [];
    Object.defineProperty(window, "location", {
      configurable: true, value: { set href(url: string) { sentTo.push(url); } } });
    onOneDrive({ drive_access: false }, {
      "POST /api/drive-watch/consent/": { authorization_url: "https://login.microsoftonline.test/c" },
    });
    expect(await screen.findByText("1. Let the app read your OneDrive")).toBeInTheDocument();
    expect(screen.getByText(/folders show here once access is allowed/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Allow OneDrive access/ }));
    await waitFor(() => expect(sentTo).toEqual(["https://login.microsoftonline.test/c"]));
  });

  it("points at Email settings when no Microsoft 365 account is connected", async () => {
    onOneDrive({ google_connected: false, drive_access: false, drive_account: "" });
    expect(await screen.findByText(/Connect your Microsoft 365 account first/)).toBeInTheDocument();
  });

  it("browses into a folder, checks it, then watches it", async () => {
    const user = userEvent.setup();
    const fetchMock = onOneDrive({}, {
      "POST /api/drive-watch/check/": { folder_id: "01MEET", name: "Meetings", files: 4,
                                        readable: 3, truncated: false, in_subfolders: 1 },
      "POST /api/drive-watch/": { ...HEALTH, provider: "microsoft", folder_name: "Meetings" },
    });
    // The root offers no "Use": OneDrive itself is not a notes folder.
    expect(await screen.findByRole("button", { name: /Documents/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Use/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Meetings/ }));
    expect(await screen.findByRole("button", { name: /Clients/ })).toBeInTheDocument();
    expect(screen.getByText(/3 files here, 2 readable/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Use “Meetings”" }));
    expect(await screen.findByText(/4 files · 3 readable as meeting notes/)).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.url.endsWith("/check/"))?.body)
      .toEqual({ folder: "01MEET" });

    await user.click(screen.getByRole("button", { name: "Watch this folder" }));
    await waitFor(() => expect(screen.getByText(/Watching “Meetings”/)).toBeInTheDocument());
    expect(fetchMock.calls.find((c) => c.method === "POST"
      && c.url.endsWith("/api/drive-watch/"))?.body).toEqual({ folder: "01MEET" });
  });

  it("goes back up from a folder", async () => {
    const user = userEvent.setup();
    onOneDrive({});
    await user.click(await screen.findByRole("button", { name: /Meetings/ }));
    await user.click(await screen.findByRole("button", { name: /Up one folder/ }));
    expect(await screen.findByRole("button", { name: /Documents/ })).toBeInTheDocument();
  });
});
