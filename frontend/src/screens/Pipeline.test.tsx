import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PIPELINES, aContact } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Pipeline } from "./Pipeline";

const SALES = PIPELINES[0];
const ENTRY = SALES.stages[0];   // Initial Contact Made
const QUAL = SALES.stages[1];    // Qualified, semantic "qualified"
const LOST = {
  id: "s-lost", pipeline: "p-sales", code: "closed_lost", label: "Closed Lost",
  semantic: "lost" as const, position: 9, is_terminal: true,
};

const DANA = aContact({ id: "dana", first_name: "Dana", last_name: "Reyes" });

function board() {
  return {
    pipeline: { ...SALES, stages: [ENTRY, QUAL, LOST] },
    columns: [
      { stage: ENTRY, count: 1, contacts: [DANA] },
      { stage: QUAL, count: 0, contacts: [] },
      { stage: LOST, count: 0, contacts: [] },
    ],
  };
}

function setup() {
  const fetchMock = mockApi({
    "/api/pipelines/p-sales/board/": board(),
    "/api/pipelines/": PIPELINES,
    "POST /api/contacts/dana/change-stage/": { contact: DANA, changed: true },
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Pipeline />);
  return fetchMock;
}

/** HTML5 drag-and-drop, with the dataTransfer jsdom does not provide. */
function dragCardTo(card: HTMLElement, column: HTMLElement) {
  const dataTransfer = { effectAllowed: "", setData: vi.fn(), getData: () => "dana" };
  fireEvent.dragStart(card, { dataTransfer });
  fireEvent.dragOver(column, { dataTransfer });
  fireEvent.drop(column, { dataTransfer });
}

function columnFor(label: string) {
  return screen.getByRole("heading", { name: label, level: 4 })
    .closest(".col") as HTMLElement;
}

function postedMoves(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.calls.filter((c) => c.method === "POST");
}

describe("Pipeline board", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("opens the contact when the card's name is clicked", async () => {
    setup();
    const link = await screen.findByRole("link", { name: "Dana Reyes" });
    expect(link).toHaveAttribute("href", "/contacts/dana");
  });

  it("moves a contact when its card is dropped on another column", async () => {
    const fetchMock = setup();
    await screen.findByRole("link", { name: "Dana Reyes" });

    dragCardTo(screen.getByRole("link", { name: "Dana Reyes" }).closest(".item")!,
               columnFor("Qualified"));

    await waitFor(() => expect(postedMoves(fetchMock)).toHaveLength(1));
    expect(postedMoves(fetchMock)[0]).toMatchObject({
      url: "/api/contacts/dana/change-stage/",
      body: { stage: "s-qual", reason: "" },
    });
  });

  it("does not move anything when dropped on the column it is already in", async () => {
    const fetchMock = setup();
    await screen.findByRole("link", { name: "Dana Reyes" });

    dragCardTo(screen.getByRole("link", { name: "Dana Reyes" }).closest(".item")!,
               columnFor("Initial Contact Made"));

    expect(postedMoves(fetchMock)).toHaveLength(0);
  });

  it("opens the panel for a reason instead of moving straight to a lost stage", async () => {
    // FR-1.7 prompts for a reason on a lost stage. A drag that skipped the
    // prompt would be a quieter way of doing the move that most deserves a note.
    const fetchMock = setup();
    await screen.findByRole("link", { name: "Dana Reyes" });

    dragCardTo(screen.getByRole("link", { name: "Dana Reyes" }).closest(".item")!,
               columnFor("Closed Lost"));

    expect(await screen.findByText(/Move Dana Reyes in Sales/)).toBeInTheDocument();
    expect(screen.getByText(/prompted on a lost stage/)).toBeInTheDocument();
    expect(postedMoves(fetchMock)).toHaveLength(0);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Reason/), "Went with an in-house hire");
    await user.click(screen.getByRole("button", { name: "Move" }));

    await waitFor(() => expect(postedMoves(fetchMock)).toHaveLength(1));
    expect(postedMoves(fetchMock)[0].body).toMatchObject({
      stage: "s-lost", reason: "Went with an in-house hire",
    });
  });

  it("keeps the move panel as a keyboard path", async () => {
    const user = userEvent.setup();
    const fetchMock = setup();

    await user.click(await screen.findByRole("button", { name: "Move Dana Reyes" }));
    await user.selectOptions(screen.getByLabelText("New stage"), "s-qual");
    await user.click(screen.getByRole("button", { name: "Move" }));

    await waitFor(() => expect(postedMoves(fetchMock)).toHaveLength(1));
    expect(postedMoves(fetchMock)[0].body).toMatchObject({ stage: "s-qual" });
  });

  it("warns before a drop that makes someone a client", async () => {
    const won = { ...QUAL, id: "s-won", code: "closed_won", label: "Closed Won",
                  semantic: "won" as const };
    const fetchMock = mockApi({
      "/api/pipelines/p-sales/board/": {
        pipeline: { ...SALES, kind: "sales", stages: [ENTRY, won] },
        columns: [
          { stage: ENTRY, count: 1, contacts: [DANA] },
          { stage: won, count: 0, contacts: [] },
        ],
      },
      "/api/pipelines/": PIPELINES,
      "POST /api/contacts/dana/change-stage/": { contact: DANA, changed: true },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Pipeline />);

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Move Dana Reyes" }));
    await user.selectOptions(screen.getByLabelText("New stage"), "s-won");

    expect(screen.getByText(/adds the client contact type and flags their company/))
      .toBeInTheDocument();
  });
});
