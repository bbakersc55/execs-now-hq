import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Budget, BudgetMonth, BudgetQuestion, Envelope, PersonalGoal } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { BudgetQuestions, PersonalGoals, PersonalOverview } from "./PersonalBudget";

const FLOW = {
  months: ["2026-04-01", "2026-05-01"], labels: ["Apr", "May"], so_far: "2026-05-01",
  rows: [{ type: "income" as const, name: "Income", cents: [1_090_000, 545_000], children: [] },
         { type: "expense" as const, name: "Housing", cents: [284_000, 284_000], children: [] }],
  in_cents: [1_090_000, 545_000], out_cents: [284_000, 284_000], net_cents: [806_000, 261_000],
};

function envelope(over: Partial<Envelope>): Envelope {
  return { id: "e1", name: "Groceries", kind: "everyday", kind_label: "Everyday", rolls: false,
           category: "c1", goal: null, source: "history", source_label: "From your history",
           planned_cents: 82_000, history_cents: 82_000, carried_cents: 0, moved_in_cents: 0,
           moved_out_cents: 0, spent_cents: 30_000, left_cents: 52_000, yearly_cents: null,
           yearly_month: null, over: false, stood: false, ...over };
}

const MONTH: BudgetMonth = {
  month: "2026-10-01", month_label: "October 2026",
  envelopes: [
    envelope({}),
    envelope({ id: "e2", name: "Dining", category: "c2", planned_cents: 23_000,
               spent_cents: 30_000, left_cents: -7_000, over: true }),
    envelope({ id: "e3", name: "Home insurance", kind: "savings", rolls: true,
               source: "yearly", planned_cents: 12_000, spent_cents: 0, left_cents: 24_000,
               carried_cents: 12_000, yearly_cents: 138_000, yearly_month: 5 }),
  ],
  income: [envelope({ id: "i1", name: "Spouse pay", kind: "income", planned_cents: 490_000,
                      spent_cents: 245_000, left_cents: 245_000 })],
  income_planned_cents: 490_000, income_received_cents: 245_000, planned_cents: 117_000,
  spent_cents: 60_000, unassigned_cents: 373_000, over_income: [], unbudgeted: [],
};

const GOAL: PersonalGoal = {
  id: "g1", name: "Car repairs", target_cents: 250_000, target_on: "2027-03-15",
  saved_cents: 90_000, set_aside_cents: 16_000, progress_cents: 106_000, percent: 42,
  monthly_cents: 16_000, monthly_chosen: false, months_of_envelopes: null,
  account: { id: "a1", name: "Joint savings" }, envelope: "e9",
  planned: { id: "p1", on_date: "2027-03-15", amount_cents: 250_000 },
};

function budget(over: Partial<Budget> = {}): Budget {
  return { has_budget: true, proposal: null, month: MONTH, goals: [GOAL], coming_up: [],
           cash_flow: FLOW, questions_waiting: 0, debts: 0, ...over };
}

const EXPLAIN = { estimate_usd: "0.0123", used_today: 2, cap: 20, refused: "" };

describe("the personal Overview (P6 M4 stop 2)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("proposes the budget from history and sets nothing until it is used", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/personal/budget": budget({ has_budget: false, month: null, proposal: {
        ready: true, least_months: 3, months: ["2026-04-01", "2026-05-01", "2026-06-01"],
        envelopes: [{ category: { id: "c1", name: "Groceries", type: "expense", parent: null,
                                  position: 0, system: false, tax_group: "",
                                  tax_group_label: "", archived: false },
                      kind: "everyday", amounts: [81_200, 79_000, 84_400],
                      proposed_cents: 81_000 }] } }),
      "POST /api/personal/budget/accept": { envelopes: 1, questions_waiting: 0 },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PersonalOverview />);
    const table = await screen.findByRole("table", { name: "Proposed budget" });
    expect(within(table).getByText("$810")).toBeInTheDocument();
    expect(within(table).getByText("From your history")).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Use this budget" }));
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.url === "/api/personal/budget/accept")).toBe(true));
  });

  it("says three months are needed before it can propose", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/personal/budget": budget({
      has_budget: false, month: null,
      proposal: { ready: false, least_months: 3, months: ["2026-09-01"], envelopes: [] } }) }));
    renderRoute(<PersonalOverview />);
    expect(await screen.findByText(/once your lines cover\s+3 months/)).toBeInTheDocument();
  });

  it("shows Planned, Spent and Left; an overspend asks where to take it from", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/personal/budget/explain": EXPLAIN,
      "GET /api/personal/budget": budget(),
      "POST /api/personal/envelopes/e2/cover": MONTH,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PersonalOverview />);
    const table = await screen.findByRole("table", { name: "Envelopes" });
    const dining = within(table).getByRole("row", { name: "Dining" });
    expect(within(dining).getByText("-$70")).toBeInTheDocument();
    expect(within(table).getByText("A yearly bill of $1,380, spread")).toBeInTheDocument();
    expect(within(table).getByText("+$120 kept from last month")).toBeInTheDocument();
    const ask = screen.getByRole("group", { name: "Dining is over" });
    await user.selectOptions(within(ask).getByLabelText("Take Dining's overspend from"), "e1");
    await user.click(within(ask).getByRole("button", { name: "Move it" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/cover"))?.body)
      .toEqual({ month: "2026-10-01", from_envelope: "e1", amount_cents: 7_000 }));
    await user.click(within(ask).getByRole("button", { name: "Let it stand" }));
    await waitFor(() => expect(fetchMock.calls.filter((c) => c.url.endsWith("/cover"))
      .at(-1)?.body).toEqual({ month: "2026-10-01", stand: true }));
  });

  it("shows Unassigned and puts it toward a goal; below zero names the envelopes over it",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "GET /api/personal/budget/explain": EXPLAIN,
        "GET /api/personal/budget": budget(),
        "POST /api/personal/budget/assign": MONTH,
      });
      vi.stubGlobal("fetch", fetchMock);
      const { unmount } = renderRoute(<PersonalOverview />);
      expect(await screen.findByText(/\$3,730 of this month's income has no job yet/))
        .toBeInTheDocument();
      await user.selectOptions(screen.getByLabelText("Put it toward"), "g1");
      await user.type(screen.getByLabelText("How much a month"), "200");
      await user.click(screen.getByRole("button", { name: "Put it there" }));
      await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/assign"))?.body)
        .toEqual({ goal: "g1", amount_cents: 20_000 }));
      unmount();
      vi.stubGlobal("fetch", mockApi({
        "GET /api/personal/budget/explain": EXPLAIN,
        "GET /api/personal/budget": budget({ month: { ...MONTH, unassigned_cents: -12_000,
          over_income: [{ id: "e1", name: "Groceries", planned_cents: 82_000 }] } }) }));
      renderRoute(<PersonalOverview />);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Your envelopes plan $120 more than your income. Over the income: Groceries ($820).");
    });

  it("has the Cash flow table by month, and Explain priced before it is pressed", async () => {
    const fetchMock = mockApi({ "GET /api/personal/budget/explain": EXPLAIN,
                                "GET /api/personal/budget": budget() });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PersonalOverview />);
    const flow = await screen.findByRole("table", { name: "Cash flow by month" });
    expect(within(flow).getByText("May so far")).toBeInTheDocument();
    expect(within(flow).getByText("$8,060")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Explain this budget (about $0.01)" }))
      .toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
  });
});

describe("the budget's questions (decision 13)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const Q: BudgetQuestion[] = [
    { id: "q1", kind: "keep", run: "proposal", state: "open", envelope: "e1", category: "c1",
      text: "Groceries have run $820 a month. Keep that, or set a target?",
      detail: { proposed_cents: 82_000 } },
    { id: "q2", kind: "normal", run: "proposal", state: "open", envelope: "e2", category: "c2",
      text: "Dining was $340 three times and $120 three times. Which is normal?",
      detail: { choices: [34_000, 12_000] } },
    { id: "q3", kind: "yearly", run: "proposal", state: "open", envelope: null, category: "c3",
      text: "This looks like a yearly bill: Home insurance, $1,380 in May. Spread it monthly?",
      detail: { cents: 138_000, month: 5, monthly_cents: 12_000 } },
    { id: "q4", kind: "coming", run: "proposal", state: "open", envelope: null, category: null,
      text: "Anything coming that your history doesn't show?", detail: {} },
  ];

  it("asks one screen at a time, each skippable, and says what an answer did", async () => {
    const user = userEvent.setup();
    let left = [...Q];
    const fetchMock = mockApi({
      "GET /api/personal/questions": Q,
      "POST /api/personal/questions/": () => {
        left = left.slice(1);
        return { status: 200, body: { said: "Done.", state: "answered", waiting: left } };
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<BudgetQuestions onClose={() => {}} />);
    expect(await screen.findByText("1 of 4")).toBeInTheDocument();
    expect(screen.getByText(Q[0].text)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Skip this one" }));
    expect(await screen.findByText(Q[1].text)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "$120 is normal" }));
    expect(await screen.findByText(Q[2].text)).toBeInTheDocument();
    expect(screen.getByText(/it is \$120 a month in\s+an envelope/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Spread it monthly" }));
    expect(await screen.findByText(Q[3].text)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "A cost on a date" }));
    await user.type(screen.getByLabelText("What is coming"), "New tires");
    await user.type(screen.getByLabelText("How much"), "900");
    await user.type(screen.getByLabelText("When"), "2027-02-01");
    await user.click(screen.getByRole("button", { name: "Add it" }));
    expect(await screen.findByText(/That's all of them/)).toBeInTheDocument();
    const posts = fetchMock.calls.filter((c) => c.method === "POST");
    expect(posts.map((c) => c.body)).toEqual([
      { skip: true }, { amount_cents: 12_000 }, { spread: true },
      { what: "planned", name: "New tires", amount_cents: 90_000, on_date: "2027-02-01" }]);
  });
});

describe("goals (decision 14)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists each goal with its progress, opens one, and adds one", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/personal/budget": budget(),
      "GET /api/personal/accounts": [{ id: "a1", name: "Joint savings", kind: "bank",
        kind_label: "Bank account", last4: "7781", closed: false, side: "personal",
        in_books: false }],
      "POST /api/personal/goals": () => ({ status: 201, body: { ...GOAL, id: "g2",
        name: "Vacation", monthly_cents: 25_000 } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PersonalGoals />);
    const card = await screen.findByRole("article", { name: "Goal: Car repairs" });
    expect(within(card).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
    expect(within(card).getByText(/\$1,060 of \$2,500/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Open" }));
    expect(screen.getByText("$2,500 on March 15, 2027")).toBeInTheDocument();
    expect(screen.getByText("Joint savings", { selector: "dd" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Goal name"), "Vacation");
    await user.type(screen.getByLabelText("Target amount"), "4000");
    await user.type(screen.getByLabelText("Amount a month"), "250");
    await user.click(screen.getByRole("button", { name: "Add the goal" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ name: "Vacation", target_on: null, saved_cents: 0, account: null,
                 target_cents: 400_000, monthly_cents: 25_000 }));
    expect(await screen.findByText(/Vacation: \$250 a month/)).toBeInTheDocument();
  });
});
