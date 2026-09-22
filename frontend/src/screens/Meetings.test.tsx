import { screen, waitFor, within } from "@testing-library/react";
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
                 has_cursor: true, files_pending: 0, files_failed: 0, files_skipped: 1 };

/** Not connected, at each of the three points the flow can be stopped at. */
const UNCONNECTED = { ...HEALTH, connected: false, folder_id: "", folder_name: "",
                      last_polled_at: null, has_cursor: false };

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
    expect(await screen.findByText(/The founder fractional connects it/))
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
