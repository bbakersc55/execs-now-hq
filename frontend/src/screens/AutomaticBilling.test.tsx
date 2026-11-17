import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkerWarning } from "../components/CardPaymentsSwitch";
import { InvoiceSchedule, PortalBilling } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ClientBilling } from "./ClientBilling";
import { Invoices } from "./Invoices";

/** 2026-11-17: recurring invoices that bill automatically. */

const sent = (fetchMock: ReturnType<typeof mockApi>, suffix: string) =>
  fetchMock.calls.filter((c) => c.method !== "GET" && c.url.endsWith(suffix)).map((c) => c.body);

beforeEach(() => { vi.unstubAllGlobals(); });

const AUTO: InvoiceSchedule = {
  id: "s2", client_company: { id: "co1", name: "Acme Fasteners" },
  contact: { id: "c1", name: "Wile Coyote" }, day_of_month: 1, next_on: "2026-12-01",
  ends_on: null, total_cents: 150000, notes: "", terms: "", terms_days: null,
  terms_label: "Net 15", pay_instructions: "", email_subject: "", email_body: "",
  is_active: true, mode: "auto", mode_label: "Bill automatically", days_of_month: [1, 15],
  first_billing_on: "2026-12-01", term_ends_on: null, lead_days: 3,
  lines: [{ description: "Operations support", quantity: "1", unit_price_cents: 150000 }],
  automatic: {
    state: "waiting", state_label: "Waiting for Acme Fasteners to agree",
    next_billing_on: "2026-12-01", last_billed_on: null,
    timing_words: "on the 1st and 15th of each month", ends_on: null, ends_set_by: "",
    timeline: [], pending: null, invited_at: null, can_run_now: false },
};
const COMPANIES = [{ id: "co1", name: "Acme Fasteners", industry: "", is_client_company: true,
                     seat_count: null, primary_contact: null }];
const PEOPLE = [{ id: "c1", first_name: "Wile", last_name: "Coyote", company: "co1" }];
const SETTINGS = { prefix: "INV-", next_value: 1, next_number: "INV-0001", terms_days: 15,
                   terms_label: "Net 15", default_notes: "", default_terms: "",
                   pay_instructions: "Bank transfer.", email_subject: "", email_body: "",
                   merge_fields: [] };

function owner(schedules: InvoiceSchedule[], routes: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    // The first route whose path starts the URL answers: the specific ones first.
    ...routes,
    "POST /api/invoice-schedules/": () => ({ status: 201, body: AUTO }),
    "GET /api/invoice-schedules/": schedules, "GET /api/invoice-settings/": SETTINGS,
    "GET /api/companies/": COMPANIES, "GET /api/contacts/": PEOPLE,
    "GET /api/finance-categories/": [], "GET /api/finance-settings/": {},
    "GET /api/invoices/": { invoices: [], totals: { invoiced_cents: 0, paid_cents: 0,
                            outstanding_cents: 0, overdue_cents: 0 }, drafts_from_schedules: 0 },
    "GET /api/nmi-events/": [] });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Invoices me={aMe()} />);
  return fetchMock;
}

describe("setting up automatic billing", () => {
  it("bills on the 1st and the 15th from a first date, and sends only what bills", async () => {
    const fetchMock = owner([]);
    await userEvent.click(await screen.findByRole("button", { name: "New recurring invoice" }));
    const form = screen.getByRole("dialog", { name: "The new recurring invoice" });
    await userEvent.selectOptions(
      within(form).getByLabelText("Client company for the recurring invoice"), "co1");
    await userEvent.selectOptions(
      await within(form).findByLabelText("Recurring invoice addressed to"), "c1");
    await userEvent.click(within(form).getByLabelText("Bill automatically"));
    // No single day and no payment terms: it is due on each billing date.
    expect(within(form).queryByLabelText("Day of the month")).toBeNull();
    expect(within(form).queryByLabelText("Payment terms for the recurring invoice")).toBeNull();
    expect(within(form).getByLabelText("Billing day 1")).toHaveValue(1);
    await userEvent.click(within(form).getByRole("button", { name: "Add a day" }));
    await userEvent.type(within(form).getByLabelText("Billing day 2"), "15");
    await userEvent.type(within(form).getByLabelText("First billing date"), "2026-12-01");
    await userEvent.type(within(form).getByLabelText("Description of line 1"),
                         "Operations support");
    await userEvent.type(within(form).getByLabelText("Price of line 1"), "1500");
    await userEvent.click(within(form).getByRole("button", {
      name: "Save the recurring invoice" }));
    await waitFor(() => expect(sent(fetchMock, "/api/invoice-schedules/")).toHaveLength(1));
    expect(sent(fetchMock, "/api/invoice-schedules/")[0]).toEqual({
      mode: "auto", client_company: "co1", contact: "c1", cadence: "monthly", every: 1,
      weekday: null, days_of_month: [1, 15],
      first_billing_on: "2026-12-01", term_ends_on: null, lead_days: 3,
      lines: [{ description: "Operations support", quantity: "1", unit_price_cents: 150000 }] });
  });

  it("waits for the client, and the owner emails them the link", async () => {
    const fetchMock = owner([AUTO], {
      "POST /api/invoice-schedules/s2/send-link/": () => ({ body: {
        ...AUTO, message: "The link was emailed to 1 client owner." } }) });
    expect(await screen.findByText("Waiting for Acme Fasteners to agree")).toBeInTheDocument();
    expect(screen.getByText("on the 1st and 15th of each month")).toBeInTheDocument();
    // No Pause: it is ended instead, from its details.
    expect(screen.queryByRole("button", { name: /Pause the recurring invoice/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", {
      name: "Details of automatic billing for Acme Fasteners" }));
    expect(screen.queryByRole("button", { name: "Run the next billing now" })).toBeNull();
    await userEvent.click(screen.getByRole("button", {
      name: "Email Acme Fasteners the link to agree" }));
    expect(await screen.findByText("The link was emailed to 1 client owner."))
      .toBeInTheDocument();
    expect(sent(fetchMock, "/send-link/")).toHaveLength(1);
  });

  it("shows the timeline, ends earlier on a date, and stops at once only when sure",
     async () => {
    const active: InvoiceSchedule = { ...AUTO, automatic: { ...AUTO.automatic!,
      state: "active", state_label: "Active", can_run_now: true, last_billed_on: "2026-12-01",
      timeline: [{ what: "Agreed", on: "2026-11-16", by: "Wile Coyote" },
                 { what: "Month to month since", on: "2026-12-01" }] } };
    const fetchMock = owner([active], {
      "POST /api/invoice-schedules/s2/set-end/": () => ({ body: { ...active, message: "Done." } }),
      "POST /api/invoice-schedules/s2/run-now/": () => ({ body: { ...active,
        message: "Invoice INV-0007 for December 15, 2026: Thank you." } }) });
    await userEvent.click(await screen.findByRole("button", {
      name: "Details of automatic billing for Acme Fasteners" }));
    const details = screen.getByLabelText("Automatic billing for Acme Fasteners");
    expect(within(details).getByLabelText("Timeline for Acme Fasteners"))
      .toHaveTextContent("Agreed: November 16, 2026, Wile Coyote");
    await userEvent.type(within(details).getByLabelText("Last day to bill Acme Fasteners"),
                         "2026-12-20");
    await userEvent.click(within(details).getByRole("button", { name: "Set the end" }));
    await waitFor(() => expect(sent(fetchMock, "/set-end/")).toEqual([
      { ends_on: "2026-12-20" }]));
    await userEvent.click(within(details).getByRole("button", { name: "Stop now" }));
    expect(sent(fetchMock, "/set-end/")).toHaveLength(1);
    await userEvent.click(within(details).getByRole("button", {
      name: "Yes, stop billing Acme Fasteners now" }));
    await waitFor(() => expect(sent(fetchMock, "/set-end/")[1]).toEqual({ now: true }));
    await userEvent.click(within(details).getByRole("button", {
      name: "Run the next billing now" }));
    expect(await within(details).findByText(/Invoice INV-0007 for December 15/))
      .toBeInTheDocument();
  });
});

describe("automatic billing in the portal", () => {
  const WAITING: PortalBilling = {
    id: "s2", state: "waiting", what: [{ description: "Operations support",
                                         amount_cents: 150000 }],
    total_cents: 150000, timing_words: "on the 1st and 15th of each month",
    words: "I agree that Summit bills Acme Fasteners automatically, on these terms:\n"
      + "Total each time: $1,500.00.", version: "2026-11-17", key: "abc123",
    next_billing_on: null, ends_on: null, last_charge_on: null, can_withdraw: false,
    agreed_at: null, pending: null };
  const CARD = { ready: true, test_mode: false, public_key: "pub", paused: false,
                 card: { brand: "Visa", last4: "1111", expires: "10/29", added_by: "Wile",
                         added_at: "2026-11-16T10:00:00Z" },
                 autopay: null, wording: "", wording_version: "2026-10-21" };

  function portal(rows: PortalBilling[], routes: Record<string, unknown> = {}) {
    const fetchMock = mockApi({ ...routes, "GET /api/portal-billing/": rows,
                                "GET /api/portal-autopay/": CARD });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ClientBilling />);
    return fetchMock;
  }

  it("shows the terms and agrees only once the box is ticked", async () => {
    const fetchMock = portal([WAITING], { "POST /api/portal-billing/s2/agree/": () => ({
      body: [{ ...WAITING, state: "active", agreed_at: "2026-11-16T10:00:00Z" }] }) });
    expect(await screen.findByLabelText("The terms")).toHaveTextContent(
      "Total each time: $1,500.00.");
    expect(screen.getByText(/Visa ending 1111/)).toBeInTheDocument();
    const go = screen.getByRole("button", { name: "Agree and start automatic billing" });
    expect(go).toBeDisabled();
    await userEvent.click(screen.getByLabelText("I agree to these terms"));
    await userEvent.click(go);
    await waitFor(() => expect(sent(fetchMock, "/agree/")).toEqual([
      { agree: true, version: "2026-11-17", key: "abc123" }]));
    expect(await screen.findByRole("button", { name: "Stop automatic billing" }))
      .toBeInTheDocument();
  });

  it("says the dates before stopping, and offers to withdraw the notice", async () => {
    const active = { ...WAITING, state: "active" as const, agreed_at: "2026-11-16T10:00:00Z",
                     next_billing_on: "2026-12-01" };
    const preview = "Billing continues through December 31, 2026. Your last charge will be "
      + "on December 15, 2026. For an exception, contact Bryan Baker (bryan@summit.invalid).";
    const fetchMock = portal([active], {
      "GET /api/portal-billing/s2/stop-preview/": { text: preview, ends_on: "2026-12-31",
                                                    last_charge_on: "2026-12-15" },
      "POST /api/portal-billing/s2/stop/": () => ({ body: [{ ...active, state: "ending",
        ends_on: "2026-12-31", last_charge_on: "2026-12-15", can_withdraw: true }] }),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Stop automatic billing" }));
    const dialog = await screen.findByRole("dialog", { name: "Stop automatic billing?" });
    expect(dialog).toHaveTextContent(preview);
    expect(sent(fetchMock, "/stop/")).toEqual([]);
    await userEvent.click(within(dialog).getByRole("button", {
      name: "Confirm: stop automatic billing" }));
    expect(await screen.findByText(/Billing continues through December 31, 2026/))
      .toHaveTextContent("Your last charge will be on December 15, 2026.");
    expect(screen.getByRole("button", { name: "Withdraw my notice" })).toBeInTheDocument();
  });

  it("shows nothing to someone it is not for", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/portal-billing/": () => ({
      status: 403, body: { detail: "Only a client owner." } }),
      "GET /api/portal-autopay/": () => ({ status: 403, body: {} }) }));
    const { container } = renderRoute(<ClientBilling />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).not.toHaveTextContent("Automatic billing");
  });
});

describe("the worker warning (2026-11-17)", () => {
  it("is red, says what each service reported and what was refused today", () => {
    render(<WorkerWarning worker={{
      production: true,
      warning: "Real calls to the card processor are OFF in the worker (NMI_LIVE_CALLS is not "
        + "true on qcluster).", web_live_calls: true,
      worker: { live_calls: false, app_environment: "production", reported_at: "x",
                minutes_ago: 3 },
      refused_today: [{ job: "billing.run_autopay", label: "Auto-pay charges (9:00)",
                        practices: 1, runs: 2 }] }} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("OFF in the worker");
    expect(alert).toHaveTextContent("Web: real calls on · Worker: real calls OFF, 3 min ago");
    expect(alert).toHaveTextContent("Refused today: Auto-pay charges (9:00), 2 runs for 1 "
      + "practice");
    expect(alert.querySelector(".bad, [class*='bad']")).not.toBeNull();
  });

  it("is absent with nothing wrong", () => {
    const { container } = render(<WorkerWarning worker={{ production: true, warning: "" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("the schedule presets (2026-11-17)", () => {
  async function open(kind: "send" | "auto") {
    cleanup();
    const fetchMock = owner([]);
    await userEvent.click(await screen.findByRole("button", { name: "New recurring invoice" }));
    const form = screen.getByRole("dialog", { name: "The new recurring invoice" });
    await userEvent.selectOptions(
      within(form).getByLabelText("Client company for the recurring invoice"), "co1");
    await userEvent.selectOptions(
      await within(form).findByLabelText("Recurring invoice addressed to"), "c1");
    if (kind === "auto") await userEvent.click(within(form).getByLabelText("Bill automatically"));
    await userEvent.type(within(form).getByLabelText("Description of line 1"), "Support");
    await userEvent.type(within(form).getByLabelText("Price of line 1"), "2000");
    return { fetchMock, form };
  }
  const saved = async (fetchMock: ReturnType<typeof mockApi>, form: HTMLElement) => {
    await userEvent.click(within(form).getByRole("button", {
      name: "Save the recurring invoice" }));
    await waitFor(() => expect(sent(fetchMock, "/api/invoice-schedules/")).toHaveLength(1));
    return sent(fetchMock, "/api/invoice-schedules/")[0] as Record<string, unknown>;
  };

  it("bills weekly on the chosen weekday, the first date filled in on it", async () => {
    const { fetchMock, form } = await open("auto");
    await userEvent.selectOptions(within(form).getByLabelText("Schedule"), "weekly");
    await userEvent.selectOptions(within(form).getByLabelText("Weekday"), "4");
    const first = within(form).getByLabelText("First billing date") as HTMLInputElement;
    expect(new Date(`${first.value}T12:00:00`).getDay()).toBe(5);    // a Friday
    const body = await saved(fetchMock, form);
    expect(body).toMatchObject({ cadence: "weekly", every: 1, weekday: 4, days_of_month: [],
                                 first_billing_on: first.value });
  });

  it("bills every two weeks, quarterly from a month, yearly on a date, or every N",
     async () => {
    let { fetchMock, form } = await open("auto");
    await userEvent.selectOptions(within(form).getByLabelText("Schedule"), "quarterly");
    await userEvent.clear(within(form).getByLabelText("Day of the month it bills on"));
    await userEvent.type(within(form).getByLabelText("Day of the month it bills on"), "1");
    await userEvent.type(within(form).getByLabelText("First month"), "2027-01");
    expect(await saved(fetchMock, form)).toMatchObject({
      cadence: "monthly", every: 3, days_of_month: [1], first_billing_on: "2027-01-01" });
    ({ fetchMock, form } = await open("auto"));
    await userEvent.selectOptions(within(form).getByLabelText("Schedule"), "yearly");
    await userEvent.type(within(form).getByLabelText("Date each year"), "2027-03-31");
    expect(await saved(fetchMock, form)).toMatchObject({
      cadence: "yearly", every: 1, days_of_month: [], first_billing_on: "2027-03-31" });
    ({ fetchMock, form } = await open("auto"));
    await userEvent.selectOptions(within(form).getByLabelText("Schedule"), "custom");
    await userEvent.clear(within(form).getByLabelText("Every how many"));
    await userEvent.type(within(form).getByLabelText("Every how many"), "3");
    await userEvent.selectOptions(within(form).getByLabelText("Weekday"), "2");
    expect(await saved(fetchMock, form)).toMatchObject({ cadence: "weekly", every: 3,
                                                          weekday: 2 });
  });

  it("gives You send each invoice the same presets, and keeps Monthly as its day", async () => {
    let { fetchMock, form } = await open("send");
    expect(within(form).getByLabelText("Day of the month")).toHaveValue(1);
    expect(await saved(fetchMock, form)).toEqual({
      client_company: "co1", contact: "c1", day_of_month: 1,
      lines: [{ description: "Support", quantity: "1", unit_price_cents: 200000 }] });
    ({ fetchMock, form } = await open("send"));
    await userEvent.selectOptions(within(form).getByLabelText("Schedule"), "biweekly");
    expect(within(form).queryByLabelText("Day of the month")).toBeNull();
    expect(within(form).getByText("First invoice date")).toBeInTheDocument();
    expect(await saved(fetchMock, form)).toMatchObject({ cadence: "weekly", every: 2 });
  });

  it("says a timed one's schedule in the list", async () => {
    owner([{ ...AUTO, mode: "send", mode_label: "You send each invoice", automatic: null,
             cadence: "weekly", every: 1, weekday: 4, days_of_month: [],
             first_billing_on: "2026-11-20", timing_words: "every Friday" }]);
    expect(await screen.findByText(/every Friday/)).toBeInTheDocument();
  });
});

