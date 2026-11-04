import { screen, waitFor, within } from "@testing-library/react";
import { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BankConnection, BankOverview, FinanceAccount } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { BankConnectionsCard, BankFeedsOnImport } from "./BankConnections";

/** Bank feeds (docs/p6_bank_feeds.md): the card in Settings → Finance and the
 *  short form on Finance → Import. */

const LEDGERS: FinanceAccount[] = [
  { id: "a1", name: "Checking", kind: "bank", kind_label: "Bank account", last4: "4421",
    opening_balance_cents: 0, opening_on: "2026-01-01", closed: false },
  { id: "a2", name: "Business card", kind: "card", kind_label: "Credit card", last4: "",
    opening_balance_cents: 0, opening_on: "2026-01-01", closed: false }];

function connection(more: Partial<BankConnection> = {}): BankConnection {
  return {
    id: "k1", provider: "plaid", institution: "First Platypus Bank", status: "connected",
    status_label: "Connected", attention_code: "", attention_detail: "", reconnect: false,
    last_synced_at: "2026-11-04T06:00:00Z", last_checked_at: null, can_check_at: null,
    last_sync_counts: { added: 3 }, last_error: "", waiting: 0, created_at: "2026-11-01T00:00:00Z",
    disconnected_at: null,
    accounts: [
      { id: "f1", name: "Plaid Checking", official_name: "", mask: "0000", type: "depository",
        subtype: "checking", finance_account: { id: "a1", name: "Checking" }, skipped: false,
        feed_from: "2026-10-16", balance_cents: 11000, available_cents: 10000, currency: "USD",
        balance_at: "2026-11-04T06:00:00Z" },
      { id: "f2", name: "Plaid Saving", official_name: "", mask: "1111", type: "depository",
        subtype: "savings", finance_account: null, skipped: false, feed_from: null,
        balance_cents: 21000, available_cents: 20000, currency: "USD", balance_at: null }],
    ...more };
}

function overview(more: Partial<BankOverview> = {}): BankOverview {
  return { available: true, configured: true, demo: false, refusal: "",
           connections: [connection()], disconnected: [], count: 1, included: 5,
           each_after_cents: 50,
           price_line: "5 bank connections included, then $0.50 a month each", ...more };
}

function show(element: ReactElement, routes: Record<string, unknown>) {
  const fetchMock = mockApi({ "GET /api/finance-accounts/": LEDGERS, ...routes });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(element);
  return fetchMock;
}

beforeEach(() => { vi.unstubAllGlobals(); });
afterEach(() => { delete (window as { Plaid?: unknown }).Plaid; });

describe("the Bank connections card", () => {
  it("lists each connection, its accounts, balances and the count against the plan", async () => {
    show(<BankConnectionsCard />, { "GET /api/finance-bank/": overview() });
    const card = await screen.findByRole("region", { name: "Bank connection First Platypus Bank" });
    expect(within(card).getByText("Connected")).toBeInTheDocument();
    expect(within(card).getByText(/Last synced/)).toBeInTheDocument();
    expect(within(card).getByText("$110.00")).toBeInTheDocument();
    expect(screen.getByLabelText("Bank connections included")).toHaveTextContent(
      "5 bank connections included, then $0.50 a month each. You have 1 connected.");
    expect(screen.getByLabelText("Ledger account for Plaid Checking")).toHaveValue("a1");
    expect(screen.getByLabelText("Ledger account for Plaid Saving")).toHaveValue("");
  });

  it("maps an account to a ledger account, or to none", async () => {
    const fetchMock = show(<BankConnectionsCard />, {
      "GET /api/finance-bank/": overview({ connections: [connection({ waiting: 1 })] }),
      "POST /api/finance-bank/k1/mapping/": () => ({ body: connection() }) });
    expect(await screen.findByText(/Nothing is brought in until/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Ledger account for Plaid Saving"),
                                  "none");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ mapping: { f2: "" } }));
    await userEvent.selectOptions(screen.getByLabelText("Ledger account for Plaid Saving"),
                                  "a2");
    await waitFor(() => expect(fetchMock.calls.filter((c) => c.method === "POST")[1]?.body)
      .toEqual({ mapping: { f2: "a2" } }));
  });

  it("checks now, and says what it found", async () => {
    const fetchMock = show(<BankConnectionsCard />, {
      "GET /api/finance-bank/": overview(),
      "POST /api/finance-bank/k1/check/": () => ({
        body: { ...connection(), counts: { added: 2, modified: 1, removed: 0 } } }) });
    await userEvent.click(await screen.findByRole("button", { name: "Check now" }));
    expect(await screen.findByText("First Platypus Bank: 2 new, 1 changed, 0 removed."))
      .toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.url.endsWith("/k1/check/"))).toBe(true);
  });

  it("holds Check now within the hour of the last one", async () => {
    const later = new Date(Date.now() + 40 * 60 * 1000).toISOString();
    show(<BankConnectionsCard />, { "GET /api/finance-bank/": overview({
      connections: [connection({ last_checked_at: "x", can_check_at: later })] }) });
    expect(await screen.findByRole("button", { name: "Check now" })).toBeDisabled();
    expect(screen.getByText(/Checked within the hour/)).toBeInTheDocument();
  });

  it("offers Reconnect in update mode when the bank needs the owner", async () => {
    const open = vi.fn();
    window.Plaid = { create: (o) => {
      setTimeout(() => o.onSuccess("public-update", {}), 0);
      return { open, exit: vi.fn(), destroy: vi.fn() };
    } };
    const fetchMock = show(<BankConnectionsCard reconnectId="k1" />, {
      "GET /api/finance-bank/": overview({ connections: [connection({
        status: "needs_attention", status_label: "Needs attention", reconnect: true,
        attention_code: "ITEM_LOGIN_REQUIRED" })] }),
      "POST /api/finance-bank/link-token/": () => ({ body: { link_token: "link-u",
                                                             update: true } }),
      "POST /api/finance-bank/k1/reconnected/": () => ({ body: connection() }) });
    expect(await screen.findByText(/needs you to sign in to it again/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(await screen.findByText("First Platypus Bank is reconnected.")).toBeInTheDocument();
    expect(open).toHaveBeenCalled();
    expect(fetchMock.calls.find((c) => c.url.endsWith("/link-token/"))?.body)
      .toEqual({ connection: "k1" });
  });

  it("connects a bank through Plaid Link and exchanges the token on the server", async () => {
    window.Plaid = { create: (o) => {
      setTimeout(() => o.onSuccess("public-sandbox", {}), 0);
      return { open: vi.fn(), exit: vi.fn(), destroy: vi.fn() };
    } };
    const fetchMock = show(<BankConnectionsCard />, {
      "GET /api/finance-bank/": overview({ connections: [], count: 0 }),
      "POST /api/finance-bank/link-token/": () => ({ body: { link_token: "link-n",
                                                             update: false } }),
      "POST /api/finance-bank/connect/": () => ({ status: 201, body: connection() }) });
    expect(await screen.findByText("No bank connected yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect a bank" }));
    expect(await screen.findByText(/First Platypus Bank is connected/)).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.url.endsWith("/connect/"))?.body)
      .toEqual({ public_token: "public-sandbox" });
  });

  it("shows the demo's refusal from the server", async () => {
    show(<BankConnectionsCard />, {
      "GET /api/finance-bank/": overview({ demo: true, refusal: "This is the demo." }),
      "POST /api/finance-bank/link-token/": () => ({ status: 409,
                                                     body: { detail: "This is the demo." } }) });
    await userEvent.click(await screen.findByRole("button", { name: "Connect a bank" }));
    expect((await screen.findAllByText("This is the demo.")).length).toBeGreaterThan(1);
  });

  it("disconnects after asking, and keeps the entries", async () => {
    vi.stubGlobal("confirm", () => true);
    const fetchMock = show(<BankConnectionsCard />, {
      "GET /api/finance-bank/": overview(),
      "POST /api/finance-bank/k1/disconnect/": () => ({ body: connection({
        status: "disconnected" }) }) });
    await userEvent.click(await screen.findByRole("button",
                                                  { name: "Disconnect First Platypus Bank" }));
    expect(await screen.findByText(/is disconnected. Its entries are kept./))
      .toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.url.endsWith("/k1/disconnect/"))).toBe(true);
  });

  it("is hidden where the server has no bank feeds", async () => {
    const fetchMock = show(<BankConnectionsCard />, {
      "GET /api/finance-bank/": overview({ available: false, connections: [] }) });
    await waitFor(() => expect(fetchMock.calls.length).toBeGreaterThan(0));
    expect(screen.queryByText("Bank connections")).not.toBeInTheDocument();
  });
});

describe("bank feeds on the Import page", () => {
  it("connects from the Import page and links to the full card", async () => {
    show(<BankFeedsOnImport />, { "GET /api/finance-bank/": overview() });
    expect(await screen.findByRole("button", { name: "Connect a bank" })).toBeInTheDocument();
    expect(screen.getByText(/1 of 2/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage bank connections" }))
      .toHaveAttribute("href", "/settings/finance#bank-connections");
  });

  it("says in one line that bank feeds are not set up, where they are not", async () => {
    show(<BankFeedsOnImport />, { "GET /api/finance-bank/": overview({ available: false }) });
    expect(await screen.findByLabelText("Bank feeds")).toHaveTextContent(
      "Bank feeds aren't set up on this server yet");
    expect(screen.queryByRole("button", { name: "Connect a bank" })).not.toBeInTheDocument();
  });
});
