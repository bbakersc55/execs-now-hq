import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Board, BonusComponentRow, BonusPayload, BonusPlanHead, BonusRow } from "../lib/scorecard";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Scorecard } from "../screens/Scorecard";

const TIERS = [{ from: 0, share: 0 }, { from: 80, share: 50 }, { from: 100, share: 100 },
  { from: 110, share: 120 }];

function comp(over: Partial<BonusComponentRow>): BonusComponentRow {
  return {
    kpi: "k1", name: "Five-star reviews", kind: "count", direction: "higher", rollup: "sum",
    weight: 40, tiers: TIERS, value: 31, value_text: "31", target: 40, target_text: "40",
    expected: 27, expected_text: "27", achievement: 114, tier: 3, share: 120, earned: 288,
    readings: [], tracked: true, next: null, ...over,
  };
}

const PLAN: BonusPlanHead = {
  id: "pl1", name: "Guest services bonus", series: "s1", period: "monthly",
  period_start: "2026-10-01", period_end: "2026-10-31", period_label: "October 2026",
  days_left: 10, ended: false, closed: false, closed_at: null, closed_by: "",
  straight_line: false, cap_pct: 120, amount: 600,
};

const DEV: BonusRow = {
  membership: "m1", name: "Dev Patel", full_amount: 600, amount: 600, prorated: false,
  days_on: 31, days: 31, joined_on: null, left_on: null, earned: 504,
  next: "$1,050 more in upsells by October 31 reaches 80% of that target and earns half of its component, another $90.",
  components: [
    comp({}),
    comp({ kpi: "k2", name: "Response time", kind: "duration", direction: "lower",
      rollup: "average", weight: 30, value: 9.4, value_text: "9.4 min", target: 15,
      target_text: "15 min", expected: 15, expected_text: "15 min", achievement: 160, earned: 216 }),
    comp({ kpi: "k3", name: "Upsells", kind: "money", weight: 30, value: 2150,
      value_text: "$2,150", target: 4000, target_text: "$4,000", expected: 2710,
      expected_text: "$2,710", achievement: 79, tier: 0, share: 0, earned: 0,
      next: { text: "$1,050 more in upsells by October 31 reaches 80% of that target and earns half of its component, another $90.", gain: 90 } }),
  ],
};

const MINE: BonusPayload = {
  views: ["mine"], view: "mine", may_build: false, may_close: false,
  may_confirm_reopen: false, sees_amounts: true, practice: false,
  practice_name: "Summit Operations Partners", plan: PLAN, me: DEV,
  earlier: [{ id: "pl0", label: "September 2026", short: "September", earned: 540, full: 600, closed: true },
    { id: "plm", label: "August 2026", short: "August", earned: 600, full: 600, closed: true }],
  choices: [{ id: "pl1", label: "October 2026" }, { id: "pl0", label: "September 2026" }],
};

const BOARD: Board = {
  exists: true, company: { id: "c1", name: "Alpine Stay Co." }, week_start: "monday",
  window: { key: "this_week", label: "This week", first: "2026-10-19", last: "2026-10-25",
    text: "The week of October 19 to 25, 2026" },
  pages: [{ id: "p1", name: "Weekly scorecard", audience: "everyone" },
    { id: "p2", name: "Guest services", audience: "team" }],
  page: "p1", may_set_up: false, may_enter: false, kpis: [], notices: [],
  bonus_views: ["mine"],
};

function teamRow(name: string, membership: string, earned: number): BonusRow {
  return { ...DEV, name, membership, earned, next: null };
}

describe("bonus plans (M5 part 2)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("My bonus: earned so far, the full amount, each component, its tier and what moves it",
    async () => {
      const user = userEvent.setup();
      vi.stubGlobal("fetch", mockApi({
        "GET /api/scorecard/bonus/": MINE,
        "GET /api/scorecard/": BOARD,
      }));
      renderRoute(<Scorecard me={aMe({ role: "ECC", client_company: "c1" })} />);
      await user.click(await screen.findByRole("tab", { name: "My bonus" }));
      const hero = await screen.findByRole("region", { name: "Earned so far" });
      expect(within(hero).getByText("$504")).toBeInTheDocument();
      expect(within(hero).getByText("October 2026 · 10 days left")).toBeInTheDocument();
      expect(within(hero).getByText(/earned so far of a \$600 full-month bonus/)).toBeInTheDocument();
      expect(within(hero).getByText(/\$1,050 more in upsells/)).toBeInTheDocument();
      expect(screen.getByText(/Only you see this page/)).toBeInTheDocument();
      const reviews = screen.getByRole("region", { name: "Five-star reviews component" });
      expect(within(reviews).getByText("40% of the plan")).toBeInTheDocument();
      expect(within(reviews).getByText("of 40 this month · 27 expected by today")).toBeInTheDocument();
      expect(within(reviews).getByText("114%")).toHaveClass("bn-ok");
      expect(within(reviews).getByText("110+ · 120%")).toHaveClass("bn-tier on");
      const response = screen.getByRole("region", { name: "Response time component" });
      expect(within(response).getByText("average this month · keep under 15 min")).toBeInTheDocument();
      const upsells = screen.getByRole("region", { name: "Upsells component" });
      expect(within(upsells).getByText("79%")).toHaveClass("bn-off");
      expect(within(upsells).getByText("<80% · 0%")).toHaveClass("bn-tier zero");
      expect(within(upsells).getByText("$0")).toBeInTheDocument();
      const earlier = screen.getByRole("region", { name: "Earlier periods" });
      expect(within(earlier).getByText("September")).toBeInTheDocument();
      expect(within(earlier).getByText("$540")).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "About this plan" }))
        .toHaveTextContent("Alpine Stay Co. pays bonuses through payroll after the month closes.");
      expect(screen.getByRole("tab", { name: "My bonus" })).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("tab", { name: "Weekly scorecard" })).toHaveAttribute("aria-selected", "false");
    });

  it("My bonus asks for an earlier period when it is chosen", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/scorecard/bonus/": MINE, "GET /api/scorecard/": BOARD });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Scorecard me={aMe({ role: "ECC", client_company: "c1" })} />);
    await user.click(await screen.findByRole("tab", { name: "My bonus" }));
    await user.selectOptions(await screen.findByLabelText("Period"), "pl0");
    await waitFor(() => expect(fetchMock.calls.some((c) =>
      c.url.includes("/api/scorecard/bonus/") && c.url.includes("plan=pl0"))).toBe(true));
  });

  it("Team bonus: a row per person with achievement and dollars, no Payroll list", async () => {
    const user = userEvent.setup();
    const team: BonusPayload = { ...MINE, views: ["mine", "team"], view: "team", plan: undefined,
      me: undefined, periods: [{ key: "monthly:2026-10-01", label: "October 2026" }],
      period: "monthly:2026-10-01",
      plans: [{ plan: { ...PLAN, totals: { people: 2, earned: 924, full: 1200 } },
        rows: [teamRow("Dev Patel", "m1", 504), teamRow("Maya Ortiz", "m2", 420)] }] };
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/bonus/": team,
      "GET /api/scorecard/": { ...BOARD, bonus_views: ["mine", "team"] } }));
    renderRoute(<Scorecard me={aMe({ role: "ECC", client_company: "c1" })} />);
    await user.click(await screen.findByRole("tab", { name: "Team bonus" }));
    const table = await screen.findByRole("table", { name: "Guest services bonus people" });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Dev Patel");
    expect(rows[1]).toHaveTextContent("$504");
    expect(rows[2]).toHaveTextContent("Maya Ortiz");
    expect(rows[2]).toHaveTextContent("70%");    // overall: 420 of 600
    expect(screen.queryByRole("region", { name: "Payroll list" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New plan" })).toBeNull();
    expect(screen.getByText(/924 earned of \$1,200 for 2 people/)).toBeInTheDocument();
  });

  it("All bonuses: a closed period's Payroll list and its spreadsheet, and the practice's tools",
    async () => {
      const user = userEvent.setup();
      const closed = { ...PLAN, closed: true, ended: true, days_left: 0,
        closed_at: "2026-10-01T10:00:00Z", closed_by: "Elena Brooks",
        totals: { people: 1, earned: 504, full: 600 }, next_exists: false };
      const all: BonusPayload = { ...MINE, views: ["all"], view: "all", plan: undefined,
        me: undefined, may_build: true, may_close: true, practice: true,
        editor: { kpis: [], members: [] },
        periods: [{ key: "monthly:2026-09-01", label: "September 2026" }],
        period: "monthly:2026-09-01", plans: [{ plan: closed, rows: [teamRow("Dev Patel", "m1", 504)] }],
        payroll: [{ name: "Dev Patel", plan: "Guest services bonus", period: "September 2026", earned: 504 }] };
      const fetchMock = mockApi({ "GET /api/scorecard/bonus/": all,
        "POST /api/scorecard/bonus/plans/pl1/copy-forward/": { id: "pl2" },
        "GET /api/scorecard/": { ...BOARD, bonus_views: ["all"] } });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<Scorecard me={aMe({ role: "FF" })} />, { path: "/companies/:id/scorecard",
        route: "/companies/c1/scorecard" });
      await user.click(await screen.findByRole("tab", { name: "All bonuses" }));
      const payroll = await screen.findByRole("region", { name: "Payroll list" });
      expect(within(payroll).getByRole("table", { name: "Payroll" })).toHaveTextContent("Dev Patel");
      expect(within(payroll).getByRole("link", { name: "Download spreadsheet" }))
        .toHaveAttribute("href", "/api/scorecard/bonus/payroll/?company=c1&period=monthly%3A2026-09-01");
      expect(screen.getByRole("button", { name: "New plan" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();     // closed
      expect(screen.queryByRole("button", { name: /Close the month/ })).toBeNull();
      await user.click(screen.getByRole("button", { name: "Copy forward" }));
      await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "POST"
        && c.url.endsWith("/pl1/copy-forward/"))).toBe(true));
    });

  it("an assistant sees achievement and no dollar columns", async () => {
    const user = userEvent.setup();
    const { earned: _e, amount: _a, full_amount: _f, ...noMoney } = DEV;
    const all: BonusPayload = { ...MINE, views: ["all"], view: "all", plan: undefined,
      me: undefined, sees_amounts: false, practice: true,
      periods: [{ key: "monthly:2026-10-01", label: "October 2026" }], period: "monthly:2026-10-01",
      plans: [{ plan: { ...PLAN, totals: null }, rows: [{ ...noMoney,
        components: noMoney.components.map(({ earned: _x, ...c }) => c) }] }] };
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/bonus/": all,
      "GET /api/scorecard/": { ...BOARD, bonus_views: ["all"] } }));
    renderRoute(<Scorecard me={aMe({ role: "VA" })} />, { path: "/companies/:id/scorecard",
      route: "/companies/c1/scorecard" });
    await user.click(await screen.findByRole("tab", { name: "All bonuses" }));
    const table = await screen.findByRole("table", { name: "Guest services bonus people" });
    expect(within(table).queryByText("Earned")).toBeNull();
    expect(within(table).getByText("114%")).toBeInTheDocument();
    expect(table.textContent).not.toContain("$");
  });

  it("a corrected reading after the close waits for the client owner's confirmation",
    async () => {
      const user = userEvent.setup();
      const closed = { ...PLAN, closed: true, ended: true, closed_at: "2026-10-01T10:00:00Z",
        corrections: [{ membership: "m1", name: "Dev Patel", kpi: "Upsells", period: "Sep 28",
          frozen: 900, now: 1200 }] };
      const all: BonusPayload = { ...MINE, views: ["all"], view: "all", plan: undefined,
        me: undefined, may_close: true, may_confirm_reopen: true,
        periods: [{ key: "monthly:2026-09-01", label: "September 2026" }], period: "monthly:2026-09-01",
        plans: [{ plan: closed, rows: [teamRow("Dev Patel", "m1", 504)] }], payroll: [] };
      const fetchMock = mockApi({ "GET /api/scorecard/bonus/": all,
        "POST /api/scorecard/bonus/plans/pl1/reopen/": { ok: true },
        "GET /api/scorecard/": { ...BOARD, bonus_views: ["all"] } });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<Scorecard me={aMe({ role: "FCC", client_company: "c1" })} />);
      await user.click(await screen.findByRole("tab", { name: "All bonuses" }));
      const note = await screen.findByRole("note");
      expect(note).toHaveTextContent("Dev Patel, Upsells, Sep 28: 900 at the close, 1200 now");
      const again = within(note).getByRole("button", { name: "Work them out again" });
      expect(again).toBeDisabled();
      await user.click(within(note).getByRole("checkbox"));
      await user.click(again);
      await waitFor(() => {
        const call = fetchMock.calls.find((c) => c.url.endsWith("/pl1/reopen/"));
        expect(call?.body).toEqual({ confirm: true });
      });
    });

  it("someone short of the client owner sees the correction but cannot confirm it", async () => {
    const user = userEvent.setup();
    const closed = { ...PLAN, closed: true, ended: true, closed_at: "2026-10-01T10:00:00Z",
      corrections: [{ membership: "m1", name: "Dev Patel", kpi: "Upsells", period: "Sep 28",
        frozen: 900, now: 1200 }] };
    const all: BonusPayload = { ...MINE, views: ["all"], view: "all", plan: undefined,
      me: undefined, may_confirm_reopen: false,
      periods: [{ key: "monthly:2026-09-01", label: "September 2026" }], period: "monthly:2026-09-01",
      plans: [{ plan: closed, rows: [teamRow("Dev Patel", "m1", 504)] }] };
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/bonus/": all,
      "GET /api/scorecard/": { ...BOARD, bonus_views: ["all"] } }));
    renderRoute(<Scorecard me={aMe({ role: "ECC", client_company: "c1" })} />);
    await user.click(await screen.findByRole("tab", { name: "All bonuses" }));
    const note = await screen.findByRole("note");
    expect(within(note).queryByRole("button")).toBeNull();
    expect(note).toHaveTextContent("The client owner confirms before the amounts change.");
  });

  it("no bonus tab for someone the server gives none", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/scorecard/": { ...BOARD, bonus_views: [] } }));
    renderRoute(<Scorecard me={aMe({ role: "ECC", client_company: "c1" })} />);
    await screen.findByRole("tab", { name: "Weekly scorecard" });
    expect(screen.getAllByRole("tab").map((t) => t.textContent))
      .toEqual(["Weekly scorecard", "Guest services"]);
  });
});
