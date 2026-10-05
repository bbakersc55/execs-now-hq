import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

const DANA = aContact({
  id: "dana", first_name: "Dana", last_name: "Reyes", company_name: "Acme Freight",
  emails: [
    { id: "e1", address: "old@example.invalid", is_primary: false },
    { id: "e2", address: "dana@example.invalid", is_primary: true },
  ],
  phones: [{ id: "p1", number: "18575550100", is_primary: true }],
  pipeline_positions: [{ ...aContact().pipeline_positions[0], pipeline: "p-sales" }],
});
/** In two pipelines, and with nothing but a name to show. */
const BARE = aContact({
  id: "bare", first_name: "Sam", last_name: "Okafor", title: "", company: null,
  company_name: "", emails: [], phones: [],
  pipeline_positions: [
    { ...DANA.pipeline_positions[0], pipeline: "p-sales", pipeline_name: "Sales" },
    { ...DANA.pipeline_positions[0], pipeline: "p-ref", pipeline_name: "Referral partners" },
  ],
});

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

function setup(boardBody: unknown = board()) {
  const fetchMock = mockApi({
    "/api/pipelines/p-sales/board/": boardBody,
    "/api/pipelines/": PIPELINES,
    "POST /api/contacts/dana/change-stage/": { contact: DANA, changed: true },
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Pipeline />);
  return fetchMock;
}

function cardFor(name: string) {
  return screen.getByRole("link", { name }).closest(".contact-card") as HTMLElement;
}

/** The non-drag path: the card's menu, then "Move to another stage…". */
async function openMovePanel(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole("button", { name: `Actions for ${name}` }));
  await user.click(screen.getByRole("menuitem", { name: /Move to another stage/ }));
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

    dragCardTo(screen.getByRole("link", { name: "Dana Reyes" }).closest(".contact-card")!,
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

    dragCardTo(screen.getByRole("link", { name: "Dana Reyes" }).closest(".contact-card")!,
               columnFor("Initial Contact Made"));

    expect(postedMoves(fetchMock)).toHaveLength(0);
  });

  it("opens the panel for a reason instead of moving straight to a lost stage", async () => {
    // FR-1.7 prompts for a reason on a lost stage. A drag that skipped the
    // prompt would be a quieter way of doing the move that most deserves a note.
    const fetchMock = setup();
    await screen.findByRole("link", { name: "Dana Reyes" });

    dragCardTo(screen.getByRole("link", { name: "Dana Reyes" }).closest(".contact-card")!,
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

  it("keeps the move panel as a keyboard and touch path, behind the card's menu", async () => {
    const user = userEvent.setup();
    const fetchMock = setup();

    await openMovePanel(user, "Dana Reyes");
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
    await openMovePanel(user, "Dana Reyes");
    await user.selectOptions(screen.getByLabelText("New stage"), "s-won");

    expect(screen.getByText(/adds the client contact type and flags their company/))
      .toBeInTheDocument();
  });

  it("shows company, primary email and phone on the card", async () => {
    setup();
    await screen.findByRole("link", { name: "Dana Reyes" });
    const card = cardFor("Dana Reyes");

    expect(card).toHaveTextContent("Acme Freight");
    expect(card).toHaveTextContent("dana@example.invalid");
    expect(card).not.toHaveTextContent("old@example.invalid");
    expect(card).toHaveTextContent("18575550100");
    expect(card).toHaveAttribute("draggable", "true");
  });

  it("leaves out an empty line instead of showing a dash", async () => {
    setup({
      ...board(),
      columns: [{ stage: ENTRY, count: 1, contacts: [BARE] },
                { stage: QUAL, count: 0, contacts: [] }],
    });
    await screen.findByRole("link", { name: "Sam Okafor" });
    const card = cardFor("Sam Okafor");

    expect(card.querySelectorAll(".line")).toHaveLength(0);
    expect(card).not.toHaveTextContent("—");
    expect(card).toHaveTextContent("also in Referral partners");
  });

  it("shows no 'also in' tag for a contact in one pipeline", async () => {
    setup();
    await screen.findByRole("link", { name: "Dana Reyes" });
    expect(cardFor("Dana Reyes")).not.toHaveTextContent("also in");
  });

  it("has no visible Move text on a card until its menu is opened", async () => {
    setup();
    await screen.findByRole("link", { name: "Dana Reyes" });
    expect(screen.queryByText(/Move/)).not.toBeInTheDocument();
  });

  it("opens the contact when the card is clicked, but not from its menu", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "/api/pipelines/p-sales/board/": board(),
      "/api/pipelines/": PIPELINES,
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/pipeline"]}>
          <Routes>
            <Route path="/pipeline" element={<Pipeline />} />
            <Route path="/contacts/:id" element={<p>The contact page</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "Actions for Dana Reyes" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.queryByText("The contact page")).not.toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Actions for Dana Reyes" })).toHaveFocus();

    await user.click(screen.getByText("Acme Freight"));
    expect(await screen.findByText("The contact page")).toBeInTheDocument();
  });

  it("narrows the cards and the count as you type in the search", async () => {
    const user = userEvent.setup();
    setup({
      ...board(),
      columns: [{ stage: ENTRY, count: 2, contacts: [DANA, BARE] },
                { stage: QUAL, count: 0, contacts: [] }],
    });
    await screen.findByRole("link", { name: "Dana Reyes" });

    await user.type(screen.getByLabelText("Find on this board"), "acme");

    expect(screen.getByRole("link", { name: "Dana Reyes" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sam Okafor" })).not.toBeInTheDocument();
    expect(columnFor("Initial Contact Made")).toHaveTextContent("1 of 2");
    expect(columnFor("Qualified")).toHaveTextContent("No one here");
  });

  it("loads the rest of a long column on Show more", async () => {
    const user = userEvent.setup();
    const long = (contacts: unknown[]) => ({
      ...board(), columns: [{ stage: ENTRY, count: 2, matched: 2, contacts }],
    });
    const fetchMock = mockApi({
      "/api/pipelines/p-sales/board/?expand=s-entry": long([DANA, BARE]),
      "/api/pipelines/p-sales/board/": long([DANA]),
      "/api/pipelines/": PIPELINES,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Pipeline />);

    await screen.findByRole("link", { name: "Dana Reyes" });
    expect(columnFor("Initial Contact Made")).toHaveTextContent("Showing 1 of 2");

    await user.click(screen.getByRole("button", { name: "Show more in Initial Contact Made" }));

    expect(await screen.findByRole("link", { name: "Sam Okafor" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show more/ })).not.toBeInTheDocument();
  });

  it("searches the cards a long column has not loaded", async () => {
    // Sam is past the first cards of the column, so only the server has him.
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "/api/pipelines/p-sales/board/?q=okafor": {
        ...board(), q: "okafor",
        columns: [{ stage: ENTRY, count: 143, matched: 1, contacts: [BARE] }],
      },
      "/api/pipelines/p-sales/board/": {
        ...board(), q: "",
        columns: [{ stage: ENTRY, count: 143, matched: 143, contacts: [DANA] }],
      },
      "/api/pipelines/": PIPELINES,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Pipeline />);
    await screen.findByRole("link", { name: "Dana Reyes" });

    await user.type(screen.getByLabelText("Find on this board"), "okafor");

    // Until the answer is in, it says the rest is still being searched.
    expect(columnFor("Initial Contact Made")).toHaveTextContent(/Searching 142 more/);
    expect(await screen.findByRole("link", { name: "Sam Okafor" })).toBeInTheDocument();
    expect(columnFor("Initial Contact Made")).toHaveTextContent("1 of 143");
    expect(screen.queryByText(/Searching/)).not.toBeInTheDocument();
  });
});
