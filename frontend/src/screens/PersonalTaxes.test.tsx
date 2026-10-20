import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CpaPage, PayYourself, TaxEstimate } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { ForYourCpaBothSides, PayYourselfCard, PersonalTaxes } from "./PersonalTaxes";

const INPUTS = {
  year: 2026, filing_status: "joint", state: "CO", state_rate_percent: "4.4",
  last_year_tax_cents: 6_184_000, last_year_taxable_cents: 18_620_000,
  effective_rate_percent: null, other_income_cents: 7_200_000, medical_miles: 86,
  charitable_miles: 140, hsa_cents: null,
};

const ESTIMATE: TaxEstimate = {
  year: 2026, as_of: "2026-10-19", confirm: "Estimate; confirm with your CPA.", ready: true,
  missing: [], brackets_year: 2026, brackets_note: "", inputs: INPUTS,
  statuses: { single: "Single", joint: "Married filing jointly",
              separate: "Married filing separately", head: "Head of household" },
  profit: { so_far_cents: 23_911_427, for_year_cents: 29_787_272, through: "2026-10-19",
            share_of_year: 0.8027 },
  other_income: { cents: 7_200_000, from: "typed", so_far_cents: null },
  withholding_cents: 840_000, paid_cents: 1_420_000,
  payments: [
    { id: "p1", on_date: "2026-04-15", amount_cents: 360_000, which: "federal",
      from: "practice", link: "/finance?kind=owner", quarter: 0, quarter_label: "First quarter" },
    { id: "p2", on_date: "2026-06-15", amount_cents: 70_000, which: "state",
      from: "household", link: "/finance/personal/entries", quarter: 1,
      quarter_label: "Second quarter" }],
  set_aside: { percent_per_draw: "28", saved_cents: 532_000 },
  method: "brackets", se_tax_cents: 3_085_548, se_half_cents: 1_542_774,
  gross_cents: 36_987_272, adjusted_cents: 35_444_498,
  deduction: { cents: 3_220_000, kind: "standard", standard_cents: 3_220_000,
               itemized_cents: 1_862_900 },
  taxable_cents: 32_224_498, federal_cents: 6_253_480, state_cents: 1_417_878,
  state_rate_percent: "4.4", total_cents: 10_756_906, required_cents: 9_916_906,
  still_needed_cents: 8_496_906,
  safe_harbor: { percent: 110, last_year_tax_cents: 6_184_000, target_cents: 6_802_400,
                 required_cents: 5_962_400,
                 why: "110%: last year's income was over $150,000." },
  quarters: [
    { label: "First quarter", on_date: "2026-04-15", amount_cents: 2_480_000,
      safe_harbor_cents: 1_491_000, paid_cents: 420_000, next: false, past: true },
    { label: "Second quarter", on_date: "2026-06-15", amount_cents: 2_480_000,
      safe_harbor_cents: 1_491_000, paid_cents: 500_000, next: false, past: true },
    { label: "Third quarter", on_date: "2026-09-15", amount_cents: 2_480_000,
      safe_harbor_cents: 1_491_000, paid_cents: 500_000, next: false, past: true },
    { label: "Fourth quarter", on_date: "2027-01-15", amount_cents: 2_480_000,
      safe_harbor_cents: 1_491_000, paid_cents: 0, next: true, past: false }],
  by_next: { on_date: "2027-01-15", label: "Fourth quarter", needed_cents: 8_497_000,
             safe_harbor_cents: 4_543_000 },
  draws: { average_draw_cents: 2_038_333, months_left: 2.9, draws_ahead_cents: 5_825_721,
           to_cover_cents: 7_964_906, suggested_percent: 137,
           since_last_payment_cents: { since: "2026-09-15", drawn_cents: 1_900_000,
                                       cents: 532_000 } },
  envelope: { id: "e1", planned_cents: 571_000, saved_cents: 532_000,
              needed_by_next_cents: 8_497_000, next_on: "2027-01-15", short_cents: 7_965_000,
              suggested_monthly_cents: 2_655_000, months_left: 3 },
};

describe("the Taxes page (P6 M4 stop 4, decision 21)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("is bold about being an estimate and shows the quarterly number and the Jan 15 line",
    async () => {
      vi.stubGlobal("fetch", mockApi({ "GET /api/personal/taxes": ESTIMATE }));
      renderRoute(<PersonalTaxes />);
      const note = await screen.findByRole("note", { name: "Taxes disclaimer" });
      expect(note.querySelector("strong")).toHaveTextContent(
        "Budgeting, forecasting and tax estimates only, not tax, legal or financial advice. "
        + "Confirm with your CPA.");
      // Every card carries it, in bold.
      const confirms = screen.getAllByText("Estimate; confirm with your CPA.");
      expect(confirms.length).toBeGreaterThanOrEqual(3);
      expect(confirms.every((el) => el.tagName === "STRONG")).toBe(true);
      expect(screen.getByLabelText("Needed by the next date")).toHaveTextContent(
        "By January 15, 2027 (fourth quarter): $84,970 on this year's estimate, or $45,430 "
        + "on the safe harbor, after the $14,200 paid so far.");
      const rows = within(screen.getByRole("table", { name: "Quarterly payments" }))
        .getAllByRole("row");
      expect(rows).toHaveLength(5);
      expect(rows[4]).toHaveTextContent("January 15, 2027");
      expect(rows[4]).toHaveTextContent("$24,800");
      expect(rows[4]).toHaveTextContent("next");
      expect(screen.getByRole("table", { name: "How the estimate is worked out" }))
        .toHaveTextContent("For estimated payments to cover$99,169.06");
    });

  it("shows the Tax envelope against the next date, and says when a share of each draw "
    + "cannot cover it", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/personal/taxes": ESTIMATE }));
    renderRoute(<PersonalTaxes />);
    const env = await screen.findByLabelText("The Tax envelope");
    expect(env).toHaveTextContent("Set aside so far$5,320");
    expect(env).toHaveTextContent("Needed by January 15, 2027$84,970");
    const list = screen.getByRole("list", { name: "What to set aside" });
    expect(list).toHaveTextContent("28% of the $19,000 drawn since the last estimated payment "
      + "(September 15, 2026) is $5,320.");
    expect(list).toHaveTextContent("more than every draw between now and January 15");
  });

  it("saves the year's inputs, and the set-aside", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/personal/taxes": ESTIMATE,
                                "POST /api/personal/taxes/": ESTIMATE });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PersonalTaxes />);
    const rate = await screen.findByLabelText("State rate");
    await user.clear(rate);
    await user.type(rate, "4.25");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toMatchObject({ year: 2026, filing_status: "joint", state_rate_percent: "4.25",
                       last_year_tax_cents: 6_184_000 }));
    await user.click(screen.getByRole("button", { name: "Use $26,550 a month" }));
    await waitFor(() => expect(fetchMock.calls.filter((c) => c.method === "POST")
      .map((c) => c.url)).toContain("/api/personal/taxes/envelope"));
  });

  it("asks for what is missing before it works anything out", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/personal/taxes": {
      ...ESTIMATE, ready: false, missing: ["your filing status"],
      inputs: { ...INPUTS, filing_status: "" } } }));
    renderRoute(<PersonalTaxes />);
    expect(await screen.findByText(/enter your filing status above/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Quarterly payments" })).toBeNull();
  });
});

const LOOP: PayYourself = {
  needed_cents: 875_000, envelopes_cents: 1_367_000, other_income_cents: 492_000,
  paid: { months: 6, average_cents: 2_143_092, drawn_cents: 2_038_333, spent_cents: 104_759,
          tax_cents: 213_333, start: "2026-04-01", end: "2026-09-30" },
  difference_cents: 1_268_092, pay_category: "Pay from Summit Operations Partners",
  matched: 6, forecasting: true,
  business_line: { group: "pattern:owner|out|x", amount_cents: 2_200_000,
                   cadence: "monthly", adjusted: "", on_date: "2026-10-28" },
};

describe("paying yourself on the Overview (decision 20)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says what the envelopes need and what was paid, and sets the business line from it",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "GET /api/personal/pay-yourself": LOOP,
        "POST /api/personal/pay-yourself": { ...LOOP, business_line: {
          ...LOOP.business_line!, amount_cents: 875_000 } } });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<PayYourselfCard />);
      expect(await screen.findByLabelText("Paying yourself")).toHaveTextContent(
        "Your envelopes need $8,750 a month beyond $4,920 of other income; you have paid "
        + "yourself $21,430.92 a month on average over the last 6 months.");
      expect(screen.getByText(/6 draws are matched to "Pay from Summit Operations Partners"/))
        .toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Set it to $8,750 a month" }));
      await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
        .toEqual({ amount_cents: 875_000 }));
      expect(await screen.findByText(/pay-yourself line is set/)).toBeInTheDocument();
    });

  it("says so when the practice has no cash forecast", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/personal/pay-yourself": {
      ...LOOP, forecasting: false, business_line: null } }));
    renderRoute(<PayYourselfCard />);
    expect(await screen.findByText(/cash forecast is its own module/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set it to/ })).toBeNull();
  });
});

const YEAR = new Date().getFullYear();
const PAGE: CpaPage = {
  year: YEAR,
  business: {
    year: YEAR, title: `Business income and expense worksheet, ${YEAR}, cash basis`,
    sections: [
      { title: "Income", rows: [{ name: "Consulting", amount_cents: 30_000_000, note: "",
                                  sub: false }],
        total_label: "Total income", total_cents: 30_000_000 },
      { title: "Expenses", rows: [{ name: "Miscellaneous (itemized)", amount_cents: 5_000,
                                    note: "Itemized below", sub: false },
                                  { name: "Postage", amount_cents: 5_000, note: "", sub: true }],
        total_label: "Total expenses", total_cents: 5_000 }],
    net_cents: 29_995_000, has_paid_personally: false, paid_personally: [],
    estimated: [{ on_date: `${YEAR}-04-15`, federal_cents: 360_000, state_cents: null }],
    estimated_federal_cents: 360_000, estimated_state_cents: 0,
    facts: [{ name: "Business miles", value: 2400 }], disclaimer: "Bookkeeping only.",
  },
  personal: {
    year: YEAR, inputs: INPUTS, confirm: "Estimate; confirm with your CPA.",
    groups: [
      { group: "medical", label: "Medical and dental", total_cents: 18_000, miles: 86,
        miles_label: "Medical miles",
        rows: [{ kind: "line", id: "l1", on_date: `${YEAR}-04-09`, item: "Doctors and dentists",
                 description: "BELL MEDICAL GROUP", charity: "", account: "Joint checking",
                 amount_cents: 18_000 }] },
      { group: "non_cash", label: "Non-cash donations, by charity", total_cents: 34_000,
        miles: null, miles_label: "",
        rows: [{ kind: "item", id: "i1", on_date: `${YEAR}-09-10`, item: "Non-cash donations",
                 description: "Clothing, four bags", charity: "Goodwill of Colorado",
                 account: "", amount_cents: 34_000 }] }],
    standard: { itemized_cents: 52_000, standard_cents: 3_220_000, status: "joint",
                status_label: "Married filing jointly", figures_year: YEAR,
                note: "The itemized total is before any limits your CPA applies. Whether to "
                  + "itemize: ask your CPA.", figures_note: "" },
    facts: [
      { key: "estimated", label: "Estimated tax payments, by quarter", total_cents: 360_000,
        note: "Ask your CPA.",
        quarters: [{ label: "First quarter", due_on: `${YEAR}-04-15`, total_cents: 360_000,
                     payments: [{ on_date: `${YEAR}-04-15`, which: "federal",
                                  from: "practice", amount_cents: 360_000 }] }] },
      { key: "hsa", label: "HSA contributions", total_cents: null, note: "Ask your CPA." }],
  },
};

describe("For your CPA, both sides (decisions 22 and 23)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("is one page with the business worksheet, then the personal section, and one PDF",
    async () => {
      vi.stubGlobal("fetch", mockApi({ "GET /api/personal/cpa": PAGE }));
      renderRoute(<ForYourCpaBothSides />);
      expect(await screen.findByRole("table", { name: "Business Income" }))
        .toHaveTextContent("Consulting$300,000.00");
      expect(screen.getByRole("link", { name: "Download the PDF, both sections" }))
        .toHaveAttribute("href", `/api/personal/cpa/pdf?year=${YEAR}`);
      expect(screen.getByRole("link", { name: "The business worksheet alone (CSV)" }))
        .toHaveAttribute("href", `/api/finance-reports/export-worksheet/?year=${YEAR}`);
      const gifts = screen.getByRole("table", { name: "Non-cash donations, by charity" });
      expect(gifts).toHaveTextContent("Goodwill of Colorado");
      expect(screen.getByLabelText("Medical miles")).toHaveValue("86");
      expect(screen.getByLabelText("Standard against itemized")).toHaveTextContent(
        `Itemized total $520; the standard deduction for married filing jointly in ${YEAR} is `
        + "$32,200.");
      expect(screen.getByText(/Whether to itemize: ask your CPA\./)).toBeInTheDocument();
      expect(screen.getByRole("group", { name: "Estimated tax payments, by quarter" }))
        .toHaveTextContent("from the practice $3,600");
    });

  it("will not add a non-cash donation without its charity", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/personal/cpa": PAGE,
                                "POST /api/personal/cpa/items": PAGE });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ForYourCpaBothSides />);
    await user.click(await screen.findByRole("button", { name: "Add a donation" }));
    const form = screen.getByRole("group", { name: "Add to Non-cash donations, by charity" });
    await user.type(within(form).getByLabelText("Description"), "A dining table");
    await user.type(within(form).getByLabelText("Amount"), "250");
    expect(within(form).getByRole("button", { name: "Add" })).toBeDisabled();
    await user.type(within(form).getByLabelText("Charity"), "Habitat ReStore");
    await user.click(within(form).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toMatchObject({ year: YEAR, tax_group: "non_cash", charity: "Habitat ReStore",
                       amount_cents: 25_000 }));
  });
});
