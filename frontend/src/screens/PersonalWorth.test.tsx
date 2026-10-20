import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Debts, Holdings, Household, NetWorth, PersonalDebt, Sides } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import {
  NetWorthCard, PersonalDebts, PersonalHousehold, PersonalRetirement, SidesCard,
} from "./PersonalWorth";

const HOUSE: Household = {
  members: [
    { id: "m1", name: "John Carter", relation: "self", relation_label: "You",
      expected_withholding_cents: null, is_you: true },
    { id: "m2", name: "Dana Carter", relation: "spouse", relation_label: "Spouse",
      expected_withholding_cents: 840_000, is_you: false }],
  things: [
    { thing: "category", id: "c1", name: "Spouse pay", what: "income", label: "Income",
      whose: "m2" },
    { thing: "debt", id: "d2", name: "Subaru Outback loan", what: "debt", label: "Car loan",
      whose: "m2" }],
  income: [{ category: "Spouse pay", whose: "m2", whose_name: "Dana Carter",
             monthly_cents: 490_000 }],
};

function debt(over: Partial<PersonalDebt>): PersonalDebt {
  return { id: "d1", name: "Home mortgage", kind: "mortgage", kind_label: "Mortgage",
           whose: null, whose_name: "Joint", balance_cents: 30_792_500,
           balance_on: "2026-09-30", balance_source: "entered", rate_percent: "6.125",
           minimum_cents: 284_000, due_day: 1, account: null,
           category: { id: "c9", name: "Rent or mortgage" }, plan_position: 2,
           payoff_on: "2037-01-01", interest_cents: 11_240_790, never: false,
           history: [{ on_date: "2026-08-31", cents: 30_918_000 },
                     { on_date: "2026-09-30", cents: 30_792_500 }],
           projected: [{ on_date: "2026-10-01", cents: 30_665_000 }], ...over };
}

const DEBTS: Debts = {
  order: "snowball", other_order: "avalanche", extra_cents: 20_000, saved_extra_cents: 20_000,
  saved_order: "snowball", total_cents: 32_445_000, minimums_cents: 335_200,
  debt_free_on: "2037-01-01", interest_cents: 11_347_271,
  other: { interest_cents: -2_883, months: 0, debt_free_on: "2037-01-01" },
  extra_saves: { interest_cents: 1_054_257, months: 10, debt_free_on: "2037-11-01" },
  debts: [debt({}),
          debt({ id: "d2", name: "Subaru Outback loan", kind: "auto", kind_label: "Car loan",
                 whose: "m2", whose_name: "Dana Carter", balance_cents: 1_652_500,
                 rate_percent: "5.900", minimum_cents: 51_200, due_day: 10,
                 plan_position: 1, payoff_on: "2028-10-10", interest_cents: 106_481 })],
};

describe("debts and the payoff plan (P6 M4 stop 3)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the plan in its order, what the other order would save, and what the extra saves",
    async () => {
      vi.stubGlobal("fetch", mockApi({ "GET /api/personal/household": HOUSE,
                                       "GET /api/personal/debts": DEBTS }));
      renderRoute(<PersonalDebts />);
      const cards = await screen.findAllByRole("heading", { level: 3 });
      expect(cards.map((h) => h.textContent)).toEqual(
        ["Personal: debts", "The payoff plan", "1. Subaru Outback loan", "2. Home mortgage"]);
      const plan = screen.getByRole("list", { name: "What the plan does" });
      expect(plan).toHaveTextContent("Highest rate first would save $28.83 in interest.");
      expect(plan).toHaveTextContent("The $200 extra saves $10,542.57 in interest and 10 "
        + "months against the minimums alone.");
      expect(screen.getByText("October 2028")).toBeInTheDocument();
      expect(screen.getByText("due on the 10th")).toBeInTheDocument();
      // The orders by name (2026-10-19), never the old ones.
      expect(screen.getByRole("button", { name: "Smallest balance first" }))
        .toHaveAttribute("aria-pressed", "true");
      expect(document.body.textContent).not.toMatch(/snowball|avalanche/i);
    });

  it("tries the other order as a look and saves only when asked", async () => {
    const user = userEvent.setup();
    const avalanche = { ...DEBTS, order: "avalanche" as const, other_order: "snowball" as const,
                        other: { interest_cents: 2_883, months: 0, debt_free_on: "2037-01-01" } };
    const fetchMock = mockApi({
      "GET /api/personal/household": HOUSE,
      "GET /api/personal/debts?order=avalanche": avalanche,
      "POST /api/personal/debts/plan": avalanche,
      "GET /api/personal/debts": DEBTS });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PersonalDebts />);
    await user.click(await screen.findByRole("button", { name: "Highest rate first" }));
    expect(await screen.findByText("Smallest balance first would cost $28.83 in interest."))
      .toBeInTheDocument();
    expect(screen.getByText("trying")).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Save the plan" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ order: "avalanche", extra_cents: 20_000 }));
  });

  it("shows one person's debts when asked", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/personal/household": HOUSE,
      "GET /api/personal/debts?whose=m2": { ...DEBTS, debts: [DEBTS.debts[1]] },
      "GET /api/personal/debts": DEBTS });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PersonalDebts />);
    await user.click(await screen.findByRole("button", { name: "Dana Carter" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "2. Home mortgage" }))
      .not.toBeInTheDocument());
    expect(fetchMock.calls.some((c) => c.url === "/api/personal/debts?whose=m2")).toBe(true);
  });
});

const HOLDINGS: Holdings = {
  assumed_return_percent: "6.00",
  estimate: "An estimate at the yearly return you assume, not a prediction and not "
    + "financial advice. Confirm with your CPA or adviser.",
  total_cents: 35_996_268,
  holdings: [
    { id: "h1", name: "Solo 401(k)", kind: "retirement", kind_label: "Retirement",
      whose: "m1", whose_name: "John Carter", balance_cents: 18_484_932,
      balance_on: "2026-09-30", target_cents: 150_000_000, target_year: 2045,
      contribution_text: "", typed_monthly_cents: 200_000,
      contributions: { monthly_cents: 200_000, recognized: false, months: [] },
      status: { on_track: false, projected_cents: 144_178_187, months: 230,
                short_cents: 5_821_813, needed_monthly_cents: 213_544,
                projection: [{ on_date: "2026-10-01", cents: 18_484_932 },
                             { on_date: "2045-12-01", cents: 144_178_187 }] },
      history: [{ on_date: "2026-09-30", cents: 18_484_932 }] },
    { id: "h2", name: "John's Roth IRA", kind: "retirement", kind_label: "Retirement",
      whose: "m1", whose_name: "John Carter", balance_cents: 4_500_401,
      balance_on: "2026-09-30", target_cents: 30_000_000, target_year: 2045,
      contribution_text: "VANGUARD ROTH", typed_monthly_cents: null,
      contributions: { monthly_cents: 50_000, recognized: true, months: [] },
      status: { on_track: true, projected_cents: 35_664_028, months: 230, short_cents: 0,
                needed_monthly_cents: 36_823, projection: [] },
      history: [{ on_date: "2026-09-30", cents: 4_500_401 }] }],
};

describe("retirement and investments (P6 M4 stop 3)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says on track or behind at the return assumed, with the estimate disclaimer", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/personal/household": HOUSE,
                                     "GET /api/personal/holdings": HOLDINGS }));
    renderRoute(<PersonalRetirement />);
    const solo = await screen.findByLabelText("Solo 401(k) in figures");
    expect(within(solo).getByText("behind")).toBeInTheDocument();
    expect(within(solo).getByText(/\$2,135\.44 a month would reach it/)).toBeInTheDocument();
    expect(within(solo).getByText("as you typed it")).toBeInTheDocument();
    const roth = screen.getByLabelText("John's Roth IRA in figures");
    expect(within(roth).getByText("on track")).toBeInTheDocument();
    expect(within(roth).getByText("seen in your lines (“VANGUARD ROTH”)")).toBeInTheDocument();
    expect(screen.getByText("6%")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("not financial advice");
  });
});

describe("the household (P6 M4 stop 3)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists people as labels, keeps the withholding, and sets whose", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "POST /api/personal/household/whose": HOUSE,
                                "POST /api/personal/household": HOUSE,
                                "GET /api/personal/household": HOUSE });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PersonalHousehold />);
    expect(await screen.findByText(/a label, not a sign-in/)).toBeInTheDocument();
    expect(screen.getByText(/Expected withholding this year: \$8,400/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Take Dana Carter out of the household" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Take John Carter out of the household" }))
      .not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Whose is Subaru Outback loan"), "");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/whose"))?.body)
      .toEqual({ thing: "debt", id: "d2", whose: null }));
  });
});

describe("the Overview's two sides and net worth (P6 M4 stop 3)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("sets both sides' cash in 90 days side by side, as numbers", async () => {
    const sides: Sides = { days: 90,
      personal: { ready: true, cash_today_cents: 14_269_183, end_cents: 20_116_828,
                  low_cents: 14_176_573, low_start: "2026-10-17" },
      business: { ready: true, cash_today_cents: 4_210_000, end_cents: 3_880_000,
                  low_cents: 2_910_000, low_start: "2026-11-30" } };
    vi.stubGlobal("fetch", mockApi({ "GET /api/personal/sides": sides }));
    renderRoute(<SidesCard />);
    expect(await screen.findByText("$201,168.28")).toBeInTheDocument();
    expect(screen.getByText("$38,800")).toBeInTheDocument();
    expect(screen.getByText(/Neither is added to the other/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("says when the practice has no cash forecast", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/personal/sides": {
      days: 90, business: null, personal: { ready: true, cash_today_cents: 1, end_cents: 2,
                                            low_cents: 1, low_start: "2026-10-17" } } }));
    renderRoute(<SidesCard />);
    expect(await screen.findByText("The practice's cash forecast is not switched on."))
      .toBeInTheDocument();
  });

  it("shows net worth over time and a home's equity", async () => {
    const worth: NetWorth = {
      as_of: "2026-10-17", assets_cents: 114_215_451, debts_cents: 32_445_000,
      total_cents: 81_770_451, assets: [], debts: [],
      series: [{ on_date: "2026-04-30", cents: 69_356_819 },
               { on_date: "2026-10-17", cents: 81_770_451 }],
      change_cents: 12_413_632, since: "2026-04-30",
      equity: [{ id: "x1", name: "The house on Aspen Court", kind: "home",
                 value_cents: 61_200_000, value_on: "2026-09-30", debt: "Home mortgage",
                 owed_cents: 30_792_500, owed_on: "2026-09-30", equity_cents: 30_407_500 }],
      things: [] };
    vi.stubGlobal("fetch", mockApi({ "GET /api/personal/household": HOUSE,
                                     "GET /api/personal/net-worth": worth }));
    renderRoute(<NetWorthCard />);
    expect(await screen.findByText("$817,704.51")).toBeInTheDocument();
    expect(screen.getByText(/up \$124,136.32 since April 30, 2026/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Equity" }))
      .toHaveTextContent("$304,075 equity");
    expect(screen.getByRole("img", { name: /Net worth: \$693,568.19/ })).toBeInTheDocument();
  });
});
