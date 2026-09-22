import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MeetingProposal } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Meetings } from "./Meetings";

const ID = "p1";

const HEALTH = { connected: true, folder_id: "folder-1", folder_name: "Meeting notes",
                 last_polled_at: "2026-09-22T09:00:00Z", last_error: "",
                 has_cursor: true, files_pending: 0, files_failed: 0, files_skipped: 1 };

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

function show(extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    [`GET /api/meeting-proposals/${ID}/`]: aProposal(),
    "GET /api/meeting-proposals/": [aProposal()],
    "GET /api/drive-watch/": HEALTH,
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Meetings me={aMe()} />);
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
