import { Forecast, ForecastLine, ForecastRow } from "../lib/api";
import { FINANCE_DISCLAIMER } from "../lib/finance";

/** A forecast for the screen's tests (P6 M2): 26 weeks from October 11,
 *  2026, flat but for three weeks made by hand, and five lines. */

export const day = (start: string, add: number) => {
  const d = new Date(`${start}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + add);
  return d.toISOString().slice(0, 10);
};

export const line = (id: string, more: Partial<ForecastLine>): ForecastLine => ({
  id, kind: "regular", direction: "out", amount_cents: 69500, on_date: "2026-10-12",
  label: "Larimer Square Cowork",
  detail: "$695.00 on the 1st, monthly: the same amount of 3 of the last 3 closed months.",
  cadence: "monthly", category: "Office expense: Coworking and meeting rooms",
  link: "/finance?category=c9&subs=0", counted: true, on_card: "",
  group: `pattern:${id}`, client: "", who: more.label ?? "Larimer Square Cowork",
  adjusted: "", adjustment: "", ...more });

export const LINES = [
  line("rent", {}),
  line("inv", { kind: "known", direction: "in", amount_cents: 680000, on_date: "2026-10-20",
                label: "Acme Fasteners: Invoice SOP-0188", cadence: "", category: "",
                group: "invoice:i1", client: "co1", who: "Acme Fasteners",
                detail: "Due October 16, 2026; forecast 4 days after its due date, as this "
                  + "client usually pays.", link: "/invoices/i1" }),
  line("visa", { kind: "card", group: "card:c1", amount_cents: 912300,
                 on_date: "2026-10-20",
                 label: "Business Visa payment", category: "",
                 detail: "What is owed on Business Visa today, $9,123.00, leaves the bank "
                   + "on the 20th, the day it is usually paid.", link: "/finance/balance" }),
  line("zoom", { amount_cents: 2199, on_date: "2026-11-04", label: "Zoom", counted: false,
                 on_card: "card1", category: "Dues and subscriptions: Software and apps" }),
  line("far", { amount_cents: 500000, on_date: "2027-02-10", label: "Far away" })];

/** 26 weeks from October 11: flat, but for two weeks made by hand. */
export function weeks(floor: number | null): ForecastRow[] {
  let cash = 1200000;
  return Array.from({ length: 26 }, (_, i) => {
    const start = day("2026-10-11", 7 * i);
    const ids = i === 0 ? ["rent"] : i === 1 ? ["inv", "visa"] : [];
    const moneyIn = i === 1 ? 680000 : 0;
    const out = i === 0 ? 69500 : i === 1 ? 912300 : i === 6 ? 1300000 : 0;
    const row = { start, end: day(start, 6), label: "", start_cents: cash,
                  in_cents: moneyIn, out_cents: out, end_cents: cash + moneyIn - out,
                  lines: ids, below_floor: floor !== null && cash + moneyIn - out < floor,
                  below_zero: cash + moneyIn - out < 0 };
    cash = row.end_cents;
    return row;
  });
}

export function aForecast(more: Partial<Forecast> = {}, floor: number | null = 1000000): Forecast {
  const w = weeks(floor);
  const low = (rows: ForecastRow[]) => {
    const least = rows.reduce((a, b) => (b.end_cents < a.end_cents ? b : a));
    return { low_cents: least.end_cents, low_start: least.start, low_label: least.label,
             end_cents: rows[rows.length - 1].end_cents,
             first_below_floor: rows.find((r) => r.below_floor)?.start ?? null,
             first_below_zero: rows.find((r) => r.below_zero)?.start ?? null };
  };
  const months: ForecastRow[] = [
    { ...w[0], end: "2026-10-31", label: "October 2026", in_cents: 680000,
      out_cents: 981800, end_cents: 898200, lines: ["rent", "inv", "visa"],
      below_floor: false, below_zero: false },
    { ...w[0], start: "2026-11-01", end: "2026-11-30", label: "November 2026",
      start_cents: 898200, in_cents: 0, out_cents: 1300000, end_cents: -401800, lines: [],
      below_floor: floor !== null, below_zero: true }];
  return {
    as_of: "2026-10-11", ready: true, closed_months: 21, closed_through: "2026-09-30",
    note: "", cash_today_cents: 1200000, unplaced_cents: 0,
    accounts: [{ id: "a1", name: "Front Range Bank checking", kind: "bank",
                 amount_cents: 1200000, last_entry_on: "2026-10-09",
                 reconciled_through: "2026-09-30", stale: false }],
    floor_cents: floor, weeks: w, months,
    views: { "30": low(w.slice(0, 5)), "90": low(w.slice(0, 13)), "180": low(w),
             months: low(months) },
    lines: LINES, left_out: [], likely_annual: [], include_client_names: false,
    planned: [], adjustments: [], clients: [{ id: "co1", name: "Acme Fasteners" }],
    history: [], what_if: null, disclaimer: FINANCE_DISCLAIMER,
    ...more };
}

export const AI = { estimate_usd: "0.0240", review_estimate_usd: "0.0610", used_today: 2,
             cap: 20, resets_at: "2026-10-12T06:00:00Z", refused: "",
             disclaimer: FINANCE_DISCLAIMER, include_client_names: false };

