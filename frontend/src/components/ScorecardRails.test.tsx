import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectorRequestModal, RailFeedModal } from "./ScorecardRails";
import { mockApi, renderRoute } from "../test/render";

const TEST = { address: null, example: "curl -X POST https://app.example/webhooks/kpi/<your address>/",
  zapier: ["Add a step: Webhooks by Zapier, then POST."], make: ["Add an HTTP module: Make a request."] };
const NO_COMPANY_HOOK = { exists: false, hint: "", keys: [], deliveries: [] };
const MCP_CONN = { id: "m1", name: "Helpdesk", url: "https://mcp.helpdesk.example/mcp", tools: ["count_tickets"],
  secret_hint: "abcd", check_ok: true, check_detail: "Connected: 1 tools.", checked_at: "2026-11-10T10:00:00Z" };
const API_CONN = { id: "a1", name: "Billing", base_url: "https://api.billing.example/v1", auth_kind: "header",
  auth_name: "Authorization", secret_hint: "wxyz", check_ok: null, check_detail: "", checked_at: null };
const AI = { estimate_usd: "0.0300", used_today: 0, cap: 20, resets_at: "", refused: "" };
const PH = ["{period_start}", "{period_end}", "{year}", "{month}"];

function open(kind: "webhook" | "mcp" | "api", owner = true) {
  return renderRoute(<RailFeedModal companyId="c1" kpiId="k1" kpiName="Tickets open" kind={kind}
    owner={owner} onClose={() => undefined} />);
}

describe("the connector rails (P13)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("a webhook's address is shown once, with the Test panel's Zapier and Make steps", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/scorecard/rails/company-webhook/": NO_COMPANY_HOOK,
      "PUT /api/scorecard/rails/webhook/": { saved: true, hint: "9f3a", token: "kh_secret9f3a",
        test: { ...TEST, address: "https://app.example/webhooks/kpi/kh_secret9f3a/",
          example: "curl -X POST https://app.example/webhooks/kpi/kh_secret9f3a/" } },
      "GET /api/scorecard/rails/webhook/": { feed: null, key: "tickets-open", test: TEST },
    });
    vi.stubGlobal("fetch", fetchMock);
    open("webhook");
    expect(await screen.findByText("Add a step: Webhooks by Zapier, then POST.")).toBeInTheDocument();
    expect(screen.getByText("Add an HTTP module: Make a request.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Each post"), "add");
    await user.type(screen.getByLabelText(/Path to the value/), "data.count");
    await user.click(screen.getByRole("button", { name: "Make the address" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual(
      { company: "c1", kpi: "k1", mode: "add", value_path: "data.count", date_path: "" }));
    expect(await screen.findByText(/This address is shown once/)).toBeInTheDocument();
    expect(screen.getByText("https://app.example/webhooks/kpi/kh_secret9f3a/")).toBeInTheDocument();
  });

  it("a saved webhook lists its deliveries and offers Rotate and Stop", async () => {
    const fetchMock = mockApi({
      "GET /api/scorecard/rails/company-webhook/": NO_COMPANY_HOOK,
      "GET /api/scorecard/rails/webhook/": { key: "tickets-open", test: TEST, feed: { active: true,
        last_run_at: null, last_error: "", last_success_at: null, mode: "replace", value_path: "",
        date_path: "", hint: "9f3a", last_received_at: "2026-11-11T09:00:00Z", deliveries: [
          { at: "2026-11-11T09:00:00Z", ok: true, what: "Week of Nov 2: saved, now 14.", received: '{"value": 14}', kpi: "" },
          { at: "2026-11-11T08:00:00Z", ok: false, what: "There is no number in value.", received: '{"v": 1}', kpi: "" }] } },
    });
    vi.stubGlobal("fetch", fetchMock);
    open("webhook");
    const table = await screen.findByRole("table", { name: "Last deliveries" });
    expect(within(table).getByText("Week of Nov 2: saved, now 14.")).toBeInTheDocument();
    expect(within(table).getByText("There is no number in value.").closest("tr")).toHaveClass("rl-bad");
    expect(screen.getByRole("button", { name: "Rotate the address" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop this feed" })).toBeInTheDocument();
    expect(screen.getByText(/Address ending …9f3a/)).toBeInTheDocument();
  });

  it("MCP: the price is shown before Claude proposes; nothing is saved until Confirm", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/scorecard/rails/mcp/": { connections: [MCP_CONN], demo: false },
      "POST /api/scorecard/rails/mcp-feed/propose/": { proposal: { tool: "count_tickets",
        arguments: { from: "{period_start}", to: "{period_end}" }, path: "open", why: "It counts tickets." },
        preview: { period: "Week of Nov 2", value: "17", answer: '{"open": 17}' } },
      "PUT /api/scorecard/rails/mcp-feed/": { feed: {}, run: { ok: true } },
      "GET /api/scorecard/rails/mcp-feed/": { feed: null, ai: AI, placeholders: PH },
    });
    vi.stubGlobal("fetch", fetchMock);
    open("mcp");
    await user.selectOptions(await screen.findByLabelText("Connection"), "m1");
    const confirm = screen.getByRole("button", { name: "Confirm and read it" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("The number you want"), "Tickets still open each week");
    await user.click(screen.getByRole("button", { name: /Propose it with Claude \(about \$0\.03/ }));
    expect(await screen.findByText(/It counts tickets/)).toBeInTheDocument();
    const preview = screen.getByLabelText("Live preview");
    expect(within(preview).getByText("17")).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.method === "PUT")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm and read it" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toMatchObject(
      { company: "c1", kpi: "k1", connection: "m1", tool: "count_tickets", value_path: "open", from_ai: true }));
    expect(await screen.findByText(/read once a day from now on/)).toBeInTheDocument();
  });

  it("MCP: the tool can be set by hand, and a failed test says why", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/scorecard/rails/mcp/m1/test/": () => ({ status: 502, body: { ...MCP_CONN, check_ok: false,
        detail: "The server took too long to answer.", tool_list: [] } }),
      "GET /api/scorecard/rails/mcp/": { connections: [MCP_CONN], demo: false },
      "POST /api/scorecard/rails/mcp-feed/preview/": { period: "Week of Nov 2", value: null, answer: "{}" },
      "GET /api/scorecard/rails/mcp-feed/": { feed: null, ai: AI, placeholders: PH },
    });
    vi.stubGlobal("fetch", fetchMock);
    open("mcp");
    await user.selectOptions(await screen.findByLabelText("Connection"), "m1");
    await user.click(screen.getByRole("button", { name: "Test connection" }));
    expect(await screen.findByText("The server took too long to answer.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Tool"), "count_tickets");
    await user.click(screen.getByRole("button", { name: "Preview it" }));
    expect(await screen.findByText("no number at that path")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and read it" })).toBeDisabled();
    expect(fetchMock.calls.find((c) => c.url.endsWith("/preview/"))?.body).toMatchObject(
      { tool: "count_tickets", from_ai: false });
  });

  it("any API: a GET with period placeholders, previewed, then saved", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/scorecard/rails/api/": { connections: [API_CONN], demo: false },
      "POST /api/scorecard/rails/api-feed/preview/": { period: "October 2026", value: "4200", answer: '{"total": 4200}' },
      "PUT /api/scorecard/rails/api-feed/": { feed: {}, run: { ok: true } },
      "GET /api/scorecard/rails/api-feed/": { feed: null, placeholders: PH },
    });
    vi.stubGlobal("fetch", fetchMock);
    open("api");
    await user.selectOptions(await screen.findByLabelText("Connection"), "a1");
    await user.type(screen.getByLabelText(/^Path \(after/), "/revenue");
    await user.type(screen.getByLabelText("Path to the value"), "total");
    await user.click(screen.getByRole("button", { name: "Preview it" }));
    expect(await screen.findByText("4200")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save and read it" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toMatchObject(
      { company: "c1", kpi: "k1", connection: "a1", method: "GET", path: "/revenue", value_path: "total" }));
  });

  it("adding an API connection puts the secret in a password field", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/scorecard/rails/api/": () => ({ status: 201, body: API_CONN }),
      "GET /api/scorecard/rails/api/": { connections: [], demo: false },
      "GET /api/scorecard/rails/api-feed/": { feed: null, placeholders: PH },
    });
    vi.stubGlobal("fetch", fetchMock);
    open("api");
    await user.click(await screen.findByRole("button", { name: "Add a connection" }));
    await user.type(screen.getByLabelText("Name"), "Billing");
    await user.type(screen.getByLabelText("Base address (https)"), "https://api.billing.example/v1");
    const secret = screen.getByLabelText("Secret");
    expect(secret).toHaveAttribute("type", "password");
    await user.type(secret, "sk_live_wxyz");
    await user.click(screen.getByRole("button", { name: "Save the connection" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual(
      { company: "c1", name: "Billing", base_url: "https://api.billing.example/v1", auth_kind: "header",
        auth_name: "", secret: "sk_live_wxyz" }));
  });

  it("an associate sees the connections but can't add or remove one", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/scorecard/rails/api/": { connections: [API_CONN], demo: false },
      "GET /api/scorecard/rails/api-feed/": { feed: null, placeholders: PH },
    }));
    open("api", false);
    expect(await screen.findByText(/The practice owner adds connections/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a connection" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove the connection/ })).toBeNull();
  });

  it("the demo says it never connects to another system", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/scorecard/rails/mcp/": { connections: [MCP_CONN], demo: true },
      "GET /api/scorecard/rails/mcp-feed/": { feed: null, ai: AI, placeholders: PH },
    }));
    open("mcp");
    expect(await screen.findByText(/never connects to another system/)).toBeInTheDocument();
  });

  it("Request a connector sends the system, the numbers and the client", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "POST /api/scorecard/rails/request/": () => ({ status: 201, body: { sent: true, id: "f1" } }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ConnectorRequestModal clientName="Pied Piper" onClose={() => undefined} />);
    expect(screen.getByRole("button", { name: "Send the request" })).toBeDisabled();
    await user.type(screen.getByLabelText("The system"), "Cloudbeds");
    await user.type(screen.getByLabelText("Which numbers you want from it"), "Occupancy and ADR");
    await user.click(screen.getByRole("button", { name: "Send the request" }));
    await waitFor(() => expect(fetchMock.calls[0].body).toMatchObject(
      { system: "Cloudbeds", numbers: "Occupancy and ADR", client: "Pied Piper" }));
    expect(await screen.findByText(/connector request/)).toBeInTheDocument();
  });
});
