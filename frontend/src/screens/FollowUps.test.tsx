import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PIPELINES, aContact } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Pipeline } from "./Pipeline";
import { StageRules } from "./StageRules";

/** Pipeline part 3: a stage's follow-up, the move's question, and Stop. */

const SALES = PIPELINES[0];
const ENTRY = SALES.stages[0];
const QUAL = SALES.stages[1];
const DANA = aContact({ id: "dana", first_name: "Dana", last_name: "Reyes",
  pipeline_positions: [{ ...aContact().pipeline_positions[0], pipeline: "p-sales" }] });
const OFFER = { stage: QUAL.id, stage_label: QUAL.label, steps: 2,
  question: `Start the ${QUAL.label} follow-up?`,
  detail: "“Proposal 1” when it starts, then “Proposal 2” 7 days after the one before is sent" };

describe("the move's question", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function board() {
    return { pipeline: { ...SALES, stages: [ENTRY, QUAL] },
      columns: [{ stage: ENTRY, count: 1, contacts: [DANA] }, { stage: QUAL, count: 0, contacts: [] }] };
  }

  async function moveDana(fetchMock: ReturnType<typeof mockApi>) {
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Pipeline />);
    const card = (await screen.findByRole("link", { name: "Dana Reyes" })).closest(".contact-card") as HTMLElement;
    const column = screen.getByRole("heading", { name: QUAL.label, level: 4 }).closest(".col") as HTMLElement;
    const dataTransfer = { effectAllowed: "", setData: vi.fn(), getData: () => "dana" };
    fireEvent.dragStart(card, { dataTransfer });
    fireEvent.dragOver(column, { dataTransfer });
    fireEvent.drop(column, { dataTransfer });
  }

  it("asks, with No first and focused, and starting is the answer yes", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "/api/pipelines/p-sales/board/": board(), "/api/pipelines/": PIPELINES,
      "POST /api/contacts/dana/change-stage/": { contact: DANA, changed: true, follow_up_offer: OFFER },
      "POST /api/contacts/dana/follow-up/": { contact: DANA, running: 1 },
    });
    await moveDana(fetchMock);
    const ask = await screen.findByRole("dialog", { name: OFFER.question });
    expect(within(ask).getByRole("button", { name: "No" })).toHaveFocus();
    await user.click(within(ask).getByRole("button", { name: "Start it" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url === "/api/contacts/dana/follow-up/"
      && (c.body as { stage: string }).stage === QUAL.id)).toBe(true));
    expect(await screen.findByText(/follow-up has started/)).toBeInTheDocument();
  });

  it("No starts nothing", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "/api/pipelines/p-sales/board/": board(), "/api/pipelines/": PIPELINES,
      "POST /api/contacts/dana/change-stage/": { contact: DANA, changed: true, follow_up_offer: OFFER },
    });
    await moveDana(fetchMock);
    await user.click(await screen.findByRole("button", { name: "No" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetchMock.calls.some((c) => c.url.includes("/follow-up/"))).toBe(false);
  });
});

describe("the follow-up on a stage card", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("sets up two steps from the library", async () => {
    const user = userEvent.setup();
    const stage = { id: "s-prop", pipeline: "p-sales", code: "proposal_given", label: "Proposal Given",
      semantic: "qualified", position: 0, is_terminal: false, contacts: 0 };
    const fetchMock = mockApi({
      "/api/pipelines/": [{ ...SALES, stages: [stage] }],
      "/api/stage-automations/examples/": [],
      "/api/stage-automations/": [],
      "PUT /api/pipeline-stages/s-prop/follow-up/": { follow_up: null },
      "/api/pipeline-stages/s-prop/follow-up/": { follow_up: null },
      "/api/email-templates/": [{ id: "t1", name: "Proposal 1", subject: "", kind: "stage" },
        { id: "t2", name: "Proposal 2", subject: "", kind: "stage" }],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<StageRules />);
    await user.click(await screen.findByRole("button", { name: "Set up the Proposal Given follow-up" }));
    await user.selectOptions(await screen.findByLabelText("Step 1 template"), "t1");
    await user.selectOptions(screen.getByLabelText("Step 2 template"), "t2");
    // Step 1 is drafted when it starts: it has no days of its own.
    expect(screen.queryByLabelText("Step 1 days after")).toBeNull();
    expect(screen.getByText("drafted into the Outbox when it starts")).toBeInTheDocument();
    expect(screen.getByLabelText("Step 2 days after")).toHaveValue(7);
    await user.click(screen.getByRole("button", { name: "Save follow-up" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual({
      steps: [{ template: "t1", days_after: 0 }, { template: "t2", days_after: 7 }], is_active: true }));
  });
});
