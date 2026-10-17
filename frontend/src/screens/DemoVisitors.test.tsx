import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AiGate, DemoEmailSettings, DemoSettingUp, DemoSettings, DemoVisitorBanner,
} from "../components/DemoVisitor";
import { DemoVisitorInfo, Me } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { DemoVisitorRow } from "./DemoVisitors";
import { Practices } from "./Practices";
import { settingsFor } from "./Settings";

const VERA: DemoVisitorRow = {
  id: "aaaaaaaa-1111-4222-8333-444444444444", name: "Vera Visitor",
  email: "vera@visiting.invalid", note: "From the call", state: "ready", state_error: "",
  created_at: "2026-10-17T16:00:00Z", expires_at: "2026-11-16T16:00:00Z",
  deletes_on: "2026-11-23T16:00:00Z", ended: false, invited_at: "2026-10-17T16:04:00Z",
  last_activity_at: null, ai_spent_today_usd: "0.40", ai_spent_total_usd: "1.10",
  reset_count: 0,
};

const DEMO: DemoVisitorInfo = {
  state: "ready", expires_at: "2026-11-16T16:00:00Z", deletes_on: "2026-11-23T16:00:00Z",
  read_only: false, ai_stop: "", ai_spent_today_usd: "0.40", ai_spent_total_usd: "1.10",
  ai_per_day_usd: "2.00", ai_in_all_usd: "10.00", reset_count: 0,
};

function visitor(demo: Partial<DemoVisitorInfo> = {}): Me {
  return aMe({ email: "vera@visiting.invalid", environment: "demo",
               demo_visitor: { ...DEMO, ...demo } });
}

/** As the app holds it: `/api/me` already answered, in the query cache. */
function withMe(me: Me, element: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["me"], me);
  return render(
    <QueryClientProvider client={client}><MemoryRouter>{element}</MemoryRouter>
    </QueryClientProvider>);
}

describe("inviting a demo visitor (2026-10-17)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("is offered in the Practices area on the demo only", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/platform/practices": [],
                                     "GET /api/platform/demo-visitors": [] }));
    const { unmount } = renderRoute(<Practices me={aMe({ environment: "production" })} />);
    await screen.findByText("No practices yet.");
    expect(screen.queryByText("Invite a demo visitor")).toBeNull();
    unmount();
    renderRoute(<Practices me={aMe({ environment: "demo" })} />);
    expect(await screen.findByText("Invite a demo visitor")).toBeInTheDocument();
    expect(await screen.findByText("No demo visitors yet.")).toBeInTheDocument();
  });

  it("sends the name, email, days and note, and says the setup has started", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/platform/practices": [],
      "POST /api/platform/demo-visitors": () => ({ status: 201,
        body: { ...VERA, state: "setting_up", invited_at: null } }),
      "GET /api/platform/demo-visitors": [],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Practices me={aMe({ environment: "demo" })} />);
    await user.type(await screen.findByLabelText("Visitor's name"), "Vera Visitor");
    await user.type(screen.getByLabelText("Visitor's email"), "vera@visiting.invalid");
    await user.type(screen.getByLabelText("Note"), "From the call");
    expect(screen.getByLabelText("Days")).toHaveValue(30);
    await user.click(screen.getByRole("button", { name: "Invite and set up their demo" }));
    expect(await screen.findByText(/Vera Visitor's demo is being set up/)).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "Vera Visitor", email: "vera@visiting.invalid", days: 30, note: "From the call" });
  });

  it("lists each copy with its visitor, dates and AI spend, and extends and deletes it",
    async () => {
      const user = userEvent.setup();
      const fetchMock = mockApi({
        "GET /api/platform/practices": [],
        "GET /api/platform/demo-visitors": [VERA],
        [`POST /api/platform/demo-visitors/${VERA.id}/extend`]: VERA,
        [`DELETE /api/platform/demo-visitors/${VERA.id}`]: () => ({ status: 204, body: null }),
      });
      vi.stubGlobal("fetch", fetchMock);
      vi.stubGlobal("confirm", vi.fn(() => true));
      renderRoute(<Practices me={aMe({ environment: "demo" })} />);
      const card = await screen.findByRole("article", { name: "Demo of Vera Visitor" });
      expect(within(card).getByText("vera@visiting.invalid")).toBeInTheDocument();
      expect(within(card).getByText("$0.40 today, $1.10 in all")).toBeInTheDocument();
      expect(within(card).getByText("Never signed in")).toBeInTheDocument();
      expect(within(card).getByText("Ready, invited")).toBeInTheDocument();
      const days = within(card).getByLabelText("Days to add for Vera Visitor");
      await user.clear(days);
      await user.type(days, "14");
      await user.click(within(card).getByRole("button", { name: "Extend" }));
      await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/extend"))?.body)
        .toEqual({ days: 14 }));
      await user.click(within(card).getByRole("button", { name: "Delete" }));
      await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "DELETE"))
        .toBe(true));
    });
});

describe("a visitor's own copy", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows only its setup page until it is ready, or says the setup did not finish",
    () => {
      const { unmount } = withMe(visitor({ state: "setting_up" }),
                                 <DemoSettingUp me={visitor({ state: "setting_up" })} />);
      expect(screen.getByText("Your demo is being set up")).toBeInTheDocument();
      unmount();
      withMe(visitor({ state: "failed" }), <DemoSettingUp me={visitor({ state: "failed" })} />);
      expect(screen.getByText("Your demo's setup did not finish")).toBeInTheDocument();
    });

  it("says whose it is and where its mail goes, and once ended that it is read-only", () => {
    const { unmount } = withMe(visitor(), <DemoVisitorBanner me={visitor()} />);
    expect(screen.getByText(/Everything it sends comes to vera@visiting.invalid/))
      .toBeInTheDocument();
    unmount();
    withMe(visitor({ read_only: true }), <DemoVisitorBanner me={visitor({ read_only: true })} />);
    expect(screen.getByText("This demo has ended.")).toBeInTheDocument();
    expect(screen.getByText(/Nothing in it can be changed/)).toBeInTheDocument();
  });

  it("offers no AI control once its AI is stopped, and says why in its place", () => {
    const button = <AiGate><button>Draft it with Claude</button></AiGate>;
    const { unmount } = withMe(visitor(), button);
    expect(screen.getByRole("button", { name: "Draft it with Claude" })).toBeInTheDocument();
    unmount();
    const stop = "This demo's AI allowance for today ($2.00) is used up. It comes back tomorrow.";
    withMe(visitor({ ai_stop: stop }), button);
    expect(screen.queryByRole("button", { name: "Draft it with Claude" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(stop);
  });

  it("an ordinary practice's AI controls are untouched", () => {
    withMe(aMe(), <AiGate><button>Draft it with Claude</button></AiGate>);
    expect(screen.getByRole("button", { name: "Draft it with Claude" })).toBeInTheDocument();
  });

  it("has Your demo in Settings, and no AI usage of its own", () => {
    const labels = settingsFor(visitor()).map((s) => s.label);
    expect(labels[0]).toBe("Your demo");
    expect(labels).not.toContain("AI usage");
    expect(settingsFor(aMe()).map((s) => s.label)).not.toContain("Your demo");
  });

  it("names what goes before Reset my demo, and resets only when confirmed", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "POST /api/demo/reset": { demo_visitor: DEMO } });
    vi.stubGlobal("fetch", fetchMock);
    withMe(visitor(), <DemoSettings me={visitor()} />);
    expect(screen.getByText(/up to \$2.00 a day and\s+\$10.00 in all/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset my demo" }));
    const dialog = screen.getByRole("dialog", { name: "Reset your demo" });
    expect(within(dialog).getByText(/the clients, their goals, projects and tasks/))
      .toBeInTheDocument();
    expect(within(dialog).getByText(/your sign-in, and the day your demo ends/))
      .toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(fetchMock.calls).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Reset my demo" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button",
      { name: "Reset my demo" }));
    await waitFor(() => expect(fetchMock.calls.map((c) => c.url)).toEqual(["/api/demo/reset"]));
  });

  it("cannot be reset once it has ended", () => {
    withMe(visitor({ read_only: true }), <DemoSettings me={visitor({ read_only: true })} />);
    expect(screen.getByRole("button", { name: "Reset my demo" })).toBeDisabled();
  });

  it("says on the Email page that it connects no Gmail or Drive", () => {
    withMe(visitor(), <DemoEmailSettings me={visitor()} />);
    expect(screen.getByText(/connects no Gmail\s+or Drive/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect/ })).toBeNull();
  });
});
