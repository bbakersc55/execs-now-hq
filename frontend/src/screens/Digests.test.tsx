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
  // Extras first: `GET /api/digests/` is a prefix of every digest route, and the
  // first matching key wins.
  const fetchMock = mockApi({ "GET /api/digests/upcoming/": [], ...extra, "GET /api/digests/": rows });
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

  it("says how long is left, not only when the window is", async () => {
    // 2026-09-18: "expires 9/18, 8:00 AM if not" was read past, and two weekly
    // digests expired unapproved. A countdown is the thing that registers.
    const sixHours = new Date(Date.now() + 6 * 60 * 60 * 1000 + 60_000).toISOString();
    show([aDigest({ send_window_at: sixHours })]);
    expect(await screen.findByText("Expires in 6 hours")).toBeInTheDocument();
    expect(screen.getByText(/its updates are owed again next period/)).toBeInTheDocument();
  });

  it("counts down an every-update draft too, which sends as soon as approved", async () => {
    const soon = new Date(Date.now() + 25 * 60 * 1000 + 30_000).toISOString();
    show([aDigest({ cadence: "every_update", send_window_at: soon })]);
    expect(await screen.findByText("Expires in 25 minutes")).toBeInTheDocument();
    expect(screen.getByText(/sends as soon as approved/)).toBeInTheDocument();
  });

  it("fires Regenerate once, however many times it is clicked", async () => {
    // The 2026-09-17 race started here: one click, two requests. The server
    // takes a row lock now, and the button stops offering the second click.
    const user = userEvent.setup();
    let release = () => {};
    const inFlight = new Promise<void>((resolve) => { release = resolve; });
    const attempts: string[] = [];
    const base = mockApi({
      "GET /api/digests/upcoming/": [],
      [`POST /api/digests/${DIGEST_ID}/regenerate/`]: aDigest(),
      "GET /api/digests/": [aDigest({ is_stale: true, stale_reason: "Overtaken." })],
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/regenerate/")) {
        attempts.push(String(input));
        await inFlight;
      }
      return base(input, init);
    }));
    renderRoute(<Digests me={aMe()} />);

    await user.click(await screen.findByRole("button", { name: "Regenerate" }));
    const busy = await screen.findByRole("button", { name: "Regenerating…" });
    expect(busy).toBeDisabled();
    await user.click(busy);                      // the second click of a double-click
    expect(attempts).toHaveLength(1);
    release();
    await waitFor(() => expect(attempts).toHaveLength(1));
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

  it("offers Generate now only on a development build", async () => {
    show([]);
    expect(await screen.findByText(/Generate a digest now/)).toBeInTheDocument();
    expect(screen.getByText(/does not exist once the app is off this laptop/)).toBeInTheDocument();
  });

  it("hides Generate now everywhere else", async () => {
    show([], aMe({ dev_tools: false }));
    await screen.findByText(/Nobody is owed an email/);
    expect(screen.queryByText(/Generate a digest now/)).not.toBeInTheDocument();
  });

  it("generates for the chosen person, period and send window", async () => {
    const user = userEvent.setup();
    const fetchMock = show([], aMe(), {
      "/api/contacts/search/": { contacts: [{ id: "c9", first_name: "Dana",
                                              last_name: "Okafor" }] },
      "POST /api/digests/generate-now/": { detail: "Generated a pending digest for Dana "
                                                   + "from 3 updates.", digest: {} },
    });
    await user.type(await screen.findByLabelText("Find a stakeholder"), "Dana");
    await user.click(await screen.findByRole("button", { name: "Dana Okafor" }));
    await user.selectOptions(screen.getByLabelText("Period in days"), "30");
    await user.selectOptions(screen.getByLabelText("Send window"), "2");
    await user.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => expect(screen.getByText(/Generated a pending digest for Dana/))
      .toBeInTheDocument());
    expect(fetchMock.calls.find((c) => c.url.endsWith("generate-now/"))?.body).toEqual({
      contact: "c9", cadence: "weekly", days: 30, send_in_minutes: 2,
    });
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


describe("is the tick running (Check 3)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const FRESH = { last_success_at: new Date().toISOString(), last_failure_at: null,
                  last_failure: "", stale: false, stale_after_minutes: 5 };

  it("warns when the tick has not run in five minutes, quoting the last failure", async () => {
    show([aDigest()], aMe(), {
      "GET /api/digests/tick-status/": {
        ...FRESH, stale: true, last_success_at: "2026-09-15T04:58:14Z",
        last_failure: "ProgrammingError: column x does not exist",
      },
    });
    expect(await screen.findByText(/has not run in the last 5 minutes/)).toBeInTheDocument();
    expect(screen.getByText(/column x does not exist/)).toBeInTheDocument();
  });

  it("says there is no record when it has never run", async () => {
    show([], aMe(), {
      "GET /api/digests/tick-status/": { ...FRESH, stale: true, last_success_at: null },
    });
    expect(await screen.findByText(/There is no record of it running/)).toBeInTheDocument();
  });

  it("stays quiet while the tick is healthy", async () => {
    const fetchMock = show([aDigest()], aMe(), { "GET /api/digests/tick-status/": FRESH });
    await screen.findByText(/Dana Okafor/);
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.includes("tick-status"))).toBe(true));
    expect(screen.queryByText(/has not run/)).not.toBeInTheDocument();
  });

  it("marks a pending digest whose window has passed", async () => {
    show([aDigest({ send_window_at: "2020-01-01T00:00:00Z" })], aMe(),
         { "GET /api/digests/tick-status/": FRESH });
    expect(await screen.findByText(/Its window has passed/)).toBeInTheDocument();
  });

  it("says an every-update digest sends as soon as it is approved", async () => {
    show([aDigest({ cadence: "every_update", send_window_at: "2099-01-01T00:00:00Z" })], aMe(),
         { "GET /api/digests/tick-status/": FRESH });
    expect(await screen.findByText(/sends as soon as approved/)).toBeInTheDocument();
    expect(screen.queryByText(/Its window has passed/)).not.toBeInTheDocument();
  });
});


describe("coming up: every-update digests waiting on their quiet window (FR-3.29a)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const HEALTHY = { last_success_at: new Date().toISOString(), last_failure_at: null,
                    last_failure: "", stale: false, stale_after_minutes: 5 };
  const CLOSES = "2026-09-15T17:49:25Z";
  const clock = (iso: string) =>
    new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const waiting = (over: Record<string, unknown> = {}) => ({
    contact: { id: "c1", name: "Bryan Baker" }, cadence: "every_update", update_count: 6,
    tasks: ["New task from ECC"], last_change_at: "2026-09-15T17:19:25Z",
    generates_at: CLOSES, due: false, ...over,
  });

  it("names the person, the cadence and when it generates", async () => {
    show([], aMe(), { "GET /api/digests/tick-status/": HEALTHY,
                      "GET /api/digests/upcoming/": [waiting()] });
    expect(await screen.findByText(
      `Bryan Baker · every update · generates at ${clock(CLOSES)} unless the task changes again`,
    )).toBeInTheDocument();
    expect(screen.getByText(/6 updates waiting/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing here has been generated or sent yet/)).toBeInTheDocument();
  });

  it("says any of several tasks, and names them", async () => {
    show([], aMe(), { "GET /api/digests/tick-status/": HEALTHY,
      "GET /api/digests/upcoming/": [waiting({ tasks: ["Fix the dock", "Replace the gate"] })] });
    expect(await screen.findByText(/unless any of these 2 tasks changes again/)).toBeInTheDocument();
    expect(screen.getByText(/on Fix the dock, Replace the gate/)).toBeInTheDocument();
  });

  it("says the next tick once the window has closed", async () => {
    show([], aMe(), { "GET /api/digests/tick-status/": HEALTHY,
                      "GET /api/digests/upcoming/": [waiting({ due: true })] });
    expect(await screen.findByText("Bryan Baker · every update · generates on the next tick"))
      .toBeInTheDocument();
  });

  it("shows nothing when nobody is waiting, and offers no control on what is", async () => {
    const fetchMock = show([aDigest()], aMe(), { "GET /api/digests/tick-status/": HEALTHY });
    await screen.findByText(/Dana Okafor/);
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.includes("upcoming"))).toBe(true));
    expect(screen.queryByText("Coming up")).not.toBeInTheDocument();

    vi.unstubAllGlobals();
    show([], aMe({ role: "VA" }), { "GET /api/digests/tick-status/": HEALTHY,
                                     "GET /api/digests/upcoming/": [waiting()] });
    const card = (await screen.findByText("Coming up")).closest(".card") ?? document.body;
    expect(card.querySelectorAll("button, input, select, textarea")).toHaveLength(0);
  });
});

describe("Preview email (development only)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("offers a preview of a pending digest, rendered exactly as it will send", async () => {
    show([aDigest()], aMe({ dev_tools: true }));
    const link = await screen.findByRole("link", { name: "Preview the email to Dana Okafor" });
    expect(link).toHaveAttribute("href", `/api/digests/${DIGEST_ID}/preview/`);
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("offers none off localhost, or once a digest is no longer pending", async () => {
    show([aDigest()], aMe({ dev_tools: false }));
    await screen.findByText(/To dana@northwind\.invalid/);
    expect(screen.queryByRole("link", { name: /Preview the email/ })).not.toBeInTheDocument();

    vi.unstubAllGlobals();
    show([aDigest({ state: "approved" })], aMe({ dev_tools: true }));
    await screen.findAllByText(/To dana@northwind\.invalid/);
    expect(screen.queryByRole("link", { name: /Preview the email/ })).not.toBeInTheDocument();
  });

  it("says that edited wording is sent without the grouping and chips", async () => {
    const user = userEvent.setup();
    show([aDigest()], aMe());
    await user.click(await screen.findByRole("button", { name: "Edit the wording" }));
    expect(screen.getByText(/Edited wording is sent as written/)).toBeInTheDocument();
  });
});
