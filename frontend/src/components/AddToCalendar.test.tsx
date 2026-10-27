import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../test/render";
import { MeetingList } from "./MeetingList";
import { AddToCalendar } from "./AddToCalendar";
import { MemoryRouter } from "react-router-dom";

function show(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{node}</MemoryRouter>
  </QueryClientProvider>);
}

describe("Add to calendar (2026-10-27)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("asks for a day, a time and a length, then says it is on the calendar", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "POST /api/calendar/add/": (body: unknown) => ({ status: 201,
      body: { web_link: "", title: (body as { title: string }).title } }) });
    vi.stubGlobal("fetch", fetchMock);
    show(<AddToCalendar source="task" sourceId="t1" date="2026-10-30" title="Send the plan" />);
    await user.click(screen.getByRole("button", { name: /Add to calendar/ }));
    await user.clear(screen.getByLabelText("Time"));
    await user.type(screen.getByLabelText("Time"), "10:30");
    await user.selectOptions(screen.getByLabelText("Length"), "45 minutes");
    await user.click(screen.getByRole("button", { name: "Add it" }));
    expect(await screen.findByText(/“Send the plan” is on your calendar, 2026-10-30 at 10:30/))
      .toBeInTheDocument();
    expect(fetchMock.calls[0].body).toEqual({ source: "task", source_id: "t1", contact: undefined,
      date: "2026-10-30", time: "10:30", minutes: 45, title: "Send the plan" });
  });

  it("opens already asked, for a stage rule, and Not now closes it", async () => {
    const user = userEvent.setup();
    const cancelled = vi.fn();
    show(<AddToCalendar open source="stage_rule" sourceId="r1" contact="c1" date="2026-10-29"
      title="Follow up with Dana" minutes={45} onCancel={cancelled} />);
    expect(screen.getByLabelText("Event title")).toHaveValue("Follow up with Dana");
    expect(screen.getByLabelText("Length")).toHaveValue("45");
    await user.click(screen.getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(cancelled).toHaveBeenCalled());
  });
});

describe("a meeting list", () => {
  it("links each matched company and contact to its record", () => {
    show(<MeetingList zone="America/Denver" events={[{
      id: "e1", title: "Weekly check-in", starts_at: "2026-10-27T16:00:00Z",
      ends_at: "2026-10-27T16:45:00Z", all_day: false, web_link: "https://calendar.test/e1",
      contacts: [{ id: "c1", name: "Dana Reyes" }], companies: [{ id: "co1", name: "Acme" }] }]} />);
    expect(screen.getByRole("link", { name: "Acme" })).toHaveAttribute("href", "/companies/co1");
    expect(screen.getByRole("link", { name: "Dana Reyes" })).toHaveAttribute("href", "/contacts/c1");
    expect(screen.getByRole("link", { name: "Weekly check-in" }))
      .toHaveAttribute("href", "https://calendar.test/e1");
    expect(screen.getByText("10:00 AM")).toBeInTheDocument();
  });
});
