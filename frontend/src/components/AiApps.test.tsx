import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderRoute } from "../test/render";
import { AiActionsCard, AiAppsCard, AiRecord, ConnectedAiApps, DoInYourAi } from "./AiApps";

const ROW = (over: Record<string, unknown> = {}) => ({
  key: "scorecard_explain", label: "Explain this scorecard", where: "Scorecard",
  started: "user", fixed: false, fixed_why: "", runs_in: "app", tier: "standard",
  default_tier: "standard",
  prompt: "Using Execs NOW HQ, read the scorecard for {record} and explain it.", ...over,
});
const ACTIONS = (rows: unknown[], may = true) => ({
  actions: rows, may_change: may,
  tiers: [{ code: "fast", label: "Fast", model: "claude-haiku-5-5" },
    { code: "standard", label: "Standard", model: "claude-sonnet-5-5" },
    { code: "deep", label: "Deep", model: "claude-opus-5-5" }],
});
const CONNECTION = { id: "c1", app: "Claude", connected_at: "2026-11-09T20:00:00Z",
  last_used_at: null, person: "Bryan Owner", role: "Practice owner" };
const URL = "https://mcp.getexecutivesnow.com/mcp";

describe("AI apps and AI actions (P7)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists every action, keeps scheduled ones fixed, and saves a change", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PATCH /api/ai/actions/": ROW({ tier: "deep" }),
      "/api/ai/actions/": ACTIONS([ROW(), ROW({ key: "digest_prose", label: "Digest prose",
        started: "unattended", fixed: true, fixed_why: "Runs on a schedule." })]),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<AiActionsCard />);
    const tier = await screen.findByLabelText("Model tier for Explain this scorecard");
    expect(screen.getByLabelText("Runs in for Explain this scorecard")).toBeInTheDocument();
    expect(screen.queryByLabelText("Runs in for Digest prose")).toBeNull();
    expect(screen.getByText(/fixed/)).toBeInTheDocument();
    await user.selectOptions(tier, "deep");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toEqual({ action: "scorecard_explain", tier: "deep" }));
  });

  it("does not let anyone but the owner change them", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/ai/actions/": ACTIONS([ROW()], false) }));
    renderRoute(<AiActionsCard />);
    expect(await screen.findByLabelText("Model tier for Explain this scorecard")).toBeDisabled();
  });

  it("keeps the in-app button while the action runs in the app", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/ai/actions/": ACTIONS([ROW()]) }));
    renderRoute(<DoInYourAi action="scorecard_explain" record="Alder"><button>Explain</button></DoInYourAi>);
    expect(await screen.findByRole("button", { name: "Explain" })).toBeInTheDocument();
  });

  it("swaps it for Do this in your AI, with the prompt naming the record", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "/api/ai/actions/": ACTIONS([ROW({ runs_in: "ai_app" })]) }));
    renderRoute(
      <AiRecord.Provider value="Alder Fasteners (company id c-1)">
        <DoInYourAi action="scorecard_explain"><button>Explain</button></DoInYourAi>
      </AiRecord.Provider>);
    await user.click(await screen.findByRole("button", { name: "Do this in your AI" }));
    expect(screen.queryByRole("button", { name: "Explain" })).toBeNull();
    const panel = screen.getByRole("region", { name: "Prompt for your AI app" });
    expect((within(panel).getByLabelText("Prompt") as HTMLTextAreaElement).value)
      .toBe("Using Execs NOW HQ, read the scorecard for Alder Fasteners (company id c-1) and explain it.");
  });

  it("shows the connector URL, the steps, and the practice's apps", async () => {
    vi.stubGlobal("fetch", mockApi({
      "/api/ai/apps/": { connector_url: URL, everyone: true, connections: [CONNECTION] },
    }));
    renderRoute(<AiAppsCard />);
    expect(await screen.findByLabelText("Connector URL")).toHaveTextContent(URL);
    expect(screen.getByText(/Settings → Connectors, then Add custom connector/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "ChatGPT" })).toBeInTheDocument();
    expect(screen.getByText("Bryan Owner")).toBeInTheDocument();
  });

  it("lists my connected apps on Profile and revokes one", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/ai/connections/c1/revoke": { revoked: true },
      "/api/ai/connections/": [CONNECTION],
      "/api/ai/apps/": { connector_url: URL, everyone: false, connections: [CONNECTION] },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ConnectedAiApps />);
    expect(await screen.findByText("Claude")).toBeInTheDocument();
    expect(screen.getByText("Not yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Revoke Claude" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "POST"
      && c.url === "/api/ai/connections/c1/revoke")).toBe(true));
  });
});
