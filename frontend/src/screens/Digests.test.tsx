import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DigestRow } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Digests } from "./Digests";

const DIGEST_ID = "5c1b2a3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";

function aDigest(overrides: Partial<DigestRow> = {}): DigestRow {
  return {
    id: DIGEST_ID,
    contact: { id: "c1", name: "Dana Okafor" },
    to_address: "dana@northwind.invalid",
    cadence: "weekly",
    state: "pending",
    is_ai_generated: false,
    is_stale: false,
    stale_reason: "",
    period_start: "2026-09-04T14:00:00Z",
    period_end: "2026-09-11T14:00:00Z",
    send_window_at: "2026-09-12T14:00:00Z",
    generated_at: "2026-09-11T14:00:00Z",
    approved_by: { id: null, name: "" },
    approved_at: null,
    item_count: 2,
    body_text: "- Map the process: not_started → in_progress\n  Invoices now clear in four days.",
    ...overrides,
  };
}

function show(rows: DigestRow[], me = aMe(), extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({ "GET /api/digests/": rows, ...extra });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Digests me={me} />);
  return fetchMock;
}

describe("the digest approval screen", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the whole rendered digest, not a summary of it", async () => {
    show([aDigest()]);
    expect(await screen.findByText(/Invoices now clear in four days/)).toBeInTheDocument();
    expect(screen.getByText(/dana@northwind.invalid/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing here has been sent/)).toBeInTheDocument();
  });

  it("AC-3.18 — a VA reads and edits, and has no approve or send control", async () => {
    show([aDigest()], aMe({ role: "VA" }));
    expect(await screen.findByText(/Invoices now clear/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit the wording" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve and send" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip this one" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve.*selected/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Approving and sending is the founder's/)).toBeInTheDocument();
  });

  it("AC-3.20 — a stale draft names what changed and offers a rebuild", async () => {
    const user = userEvent.setup();
    const fetchMock = show(
      [aDigest({ is_stale: true,
                 stale_reason: "Map the process: completed landed after this draft was written." })],
      aMe(),
      { [`POST /api/digests/${DIGEST_ID}/regenerate/`]: aDigest() },
    );
    expect(await screen.findByText(/Overtaken by events/)).toBeInTheDocument();
    expect(screen.getByText(/landed after this draft was written/)).toBeInTheDocument();
    // Still approvable as it stands: the flag informs, it does not block.
    expect(screen.getByRole("button", { name: "Approve and send" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(
      fetchMock.calls.some((c) => c.url.endsWith("/regenerate/")),
    ).toBe(true));
  });

  it("approves a batch through one call, and reports what was refused", async () => {
    const user = userEvent.setup();
    const fetchMock = show([aDigest()], aMe(), {
      "POST /api/digests/approve-selected/": { approved: [DIGEST_ID], refused: [] },
    });
    await user.click(await screen.findByLabelText(/Select the digest for Dana/));
    await user.click(screen.getByRole("button", { name: /Approve 1 selected/ }));
    await waitFor(() => expect(screen.getByText("1 approved.")).toBeInTheDocument());
    expect(fetchMock.calls.find((c) => c.url.endsWith("approve-selected/"))?.body)
      .toEqual({ ids: [DIGEST_ID] });
  });

  it("says plainly when there is nothing to send", async () => {
    show([]);
    expect(await screen.findByText(/Nobody is owed an email/)).toBeInTheDocument();
  });
});

describe("FR-3.39 — list and board", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows a column per status on the board, and filters the list", async () => {
    const user = userEvent.setup();
    const { Tasks } = await import("./Tasks");
    const { aTask } = await import("../test/fixtures");
    const fetchMock = mockApi({
      "/api/tasks/": [aTask({ title: "Waiting one", status: "waiting_on_client" }),
                      aTask({ id: "t2", title: "Blocked one", status: "blocked" })],
      "/api/projects/": [],
      "/api/portal-people/": [],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Tasks me={aMe()} />);

    expect(await screen.findByText("Waiting one")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("View"), "board");
    const board = screen.getByLabelText("Board");
    expect(board.querySelectorAll(".col")).toHaveLength(6);
    expect(board).toHaveTextContent("Waiting on client");
    expect(board).toHaveTextContent("Blocked");

    await user.selectOptions(screen.getByLabelText("Filter by status"), "blocked");
    await waitFor(() => expect(
      fetchMock.calls.some((c) => c.url.includes("status=blocked")),
    ).toBe(true));
  });
});
