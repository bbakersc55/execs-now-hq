import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderRoute } from "../test/render";
import { CalendarCard } from "./CalendarCard";

const STATUS = {
  provider: "google", provider_label: "Google Calendar", configured: true, refusal: "",
  connected: false, email_address: "", connected_provider: "", last_synced_at: null,
  last_error: "",
};

describe("Profile → Your calendar (2026-10-27)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says what is read and kept before anyone connects", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/calendar/": STATUS }));
    renderRoute(<CalendarCard />);
    expect(await screen.findByText(/No calendar is connected for you/)).toBeInTheDocument();
    expect(screen.getByText(/Never a meeting's description or notes/)).toBeInTheDocument();
    expect(screen.getByText(/The addresses are not kept, only the matches/)).toBeInTheDocument();
    expect(screen.getByText(/calendar.events/)).toBeInTheDocument();
  });

  it("sends the person to their provider to connect", async () => {
    const user = userEvent.setup();
    const sentTo: string[] = [];
    Object.defineProperty(window, "location", {
      configurable: true, value: { set href(url: string) { sentTo.push(url); } } });
    vi.stubGlobal("fetch", mockApi({
      "POST /api/calendar/start/": { authorization_url: "https://accounts.google.test/cal" },
      "GET /api/calendar/": STATUS,
    }));
    renderRoute(<CalendarCard />);
    await user.click(await screen.findByRole("button", { name: "Connect your calendar" }));
    await waitFor(() => expect(sentTo).toEqual(["https://accounts.google.test/cal"]));
  });

  it("names Microsoft's permission on a Microsoft practice, and shows the account once connected",
    async () => {
      vi.stubGlobal("fetch", mockApi({ "GET /api/calendar/": {
        ...STATUS, provider: "microsoft", provider_label: "Microsoft 365", connected: true,
        email_address: "bryan@contoso.example", last_synced_at: "2026-10-27T15:00:00Z" } }));
      renderRoute(<CalendarCard />);
      expect(await screen.findByText("bryan@contoso.example")).toBeInTheDocument();
      expect(screen.getByText(/Calendars.ReadWrite/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument();
    });

  it("on the demo, connects nothing and says why", async () => {
    const refusal = "This is the demo. It connects no calendar; Home shows the demo's own meetings.";
    vi.stubGlobal("fetch", mockApi({ "GET /api/calendar/": { ...STATUS, refusal } }));
    renderRoute(<CalendarCard />);
    expect(await screen.findByText(refusal)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect your calendar" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Disconnect" })).not.toBeInTheDocument();
    expect(screen.queryByText(/No calendar is connected for you/)).not.toBeInTheDocument();
  });
});
