import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Commitment } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { WaitingOnOthers } from "./WaitingOnOthers";

const ROW: Commitment = {
  id: "k1", state: "open", outcome: "follow_up", outcome_label: "Follow up",
  owner_name: "Tom Okafor", owner_kind: "prospect", contact: "c1", company: null,
  company_name: "", text: "Send the signed proposal", due_date: "2026-09-25",
  follow_up_date: "2026-09-25", overdue: true, task: "t1",
  meeting: { id: "m1", title: "Intro call", date: "2026-09-20" },
  source_excerpt: "Tom will send the signed proposal by Friday.", done_at: null,
};

function show(extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({ ...extra, "GET /api/commitments/": [ROW] });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<WaitingOnOthers />);
  return fetchMock;
}

/** Owner, 2026-09-28 — open commitments by other people, with done and snooze. */
describe("Waiting on others", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists who owes what, overdue marked, with where it came from", async () => {
    show();
    expect(await screen.findByRole("link", { name: "Tom Okafor" }))
      .toHaveAttribute("href", "/contacts/c1");
    expect(screen.getByText("overdue")).toBeInTheDocument();
    expect(screen.getByText("Intro call, 2026-09-20")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Follow up" })).toHaveAttribute("href", "/tasks/t1");
  });

  it("marks done and snoozes", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "POST /api/commitments/k1/snooze/": ROW,
                             "POST /api/commitments/k1/done/": ROW });
    await user.click(await screen.findByRole("button", { name: /Snooze Send the signed/ }));
    await user.click(screen.getByRole("button", { name: /Done: Send the signed/ }));
    await waitFor(() => expect(fetchMock.calls.filter((c) => c.method === "POST")
      .map((c) => [c.url, c.body])).toEqual([
        ["/api/commitments/k1/snooze/", { days: 7 }], ["/api/commitments/k1/done/", undefined]]));
  });

  it("filters to overdue", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await user.click(await screen.findByRole("button", { name: "Overdue only" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.includes("overdue=1")))
      .toBe(true));
  });
});
