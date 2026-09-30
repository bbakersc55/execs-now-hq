import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { EnrolledIn } from "./EnrolledIn";

const ROWS = [
  { kind: "referral_touches", id: "e1", label: "Referral touches",
    detail: "Monthly · next 2026-10-11", since: "2026-09-28T10:00:00Z", by: "Bryan Baker" },
  { kind: "digest", id: "s1", label: "Progress digest — goal “Cut DSO”",
    detail: "Weekly", since: "2026-09-01T10:00:00Z", by: "" },
];

function show(rows = ROWS, me = aMe(), isPartner = true, extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({ ...extra, "GET /api/contacts/c1/enrollments/": rows,
                              "GET /api/contacts/c1/suppressions/": [] });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<EnrolledIn contactId="c1" me={me} isPartner={isPartner} />);
  return fetchMock;
}

/** Owner, 2026-09-28 — every enrolment in one place, each with the way off. */
describe("Enrolled in", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists touches and digests together", async () => {
    show();
    expect(await screen.findByText("Referral touches")).toBeInTheDocument();
    expect(screen.getByText("Progress digest — goal “Cut DSO”")).toBeInTheDocument();
  });

  it("unenrols from a digest by its attachment and from touches by program", async () => {
    const user = userEvent.setup();
    const fetchMock = show(ROWS, aMe(), true, { "POST /api/contacts/c1/unenroll/": {} });
    await user.click(await screen.findByRole("button", { name: /Unenroll from Progress digest/ }));
    await user.click(screen.getByRole("button", { name: "Unenroll from Referral touches" }));

    await waitFor(() => expect(fetchMock.calls.filter((c) => c.method === "POST")
      .map((c) => c.body)).toEqual([{ stakeholder: "s1" }, { program: "referral_touches" }]));
  });

  it("offers enrolment to a partner who is not on touches", async () => {
    const user = userEvent.setup();
    const fetchMock = show([], aMe(), true, { "POST /api/contacts/c1/enroll/": {} });
    expect(await screen.findByText("Not enrolled in any email.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Enroll in referral touches" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ program: "referral_touches" }));
  });

  it("shows a VA the list and no controls", async () => {
    show(ROWS, aMe({ role: "VA" }));
    expect(await screen.findByText("Referral touches")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Unenroll/ })).not.toBeInTheDocument();
  });

  it("says what they unsubscribed from, and that only their link undoes it", async () => {
    const fetchMock = mockApi({
      "GET /api/contacts/c1/enrollments/": [],
      "GET /api/contacts/c1/suppressions/": [
        { category: "marketing", label: "marketing emails", date: "2026-09-28" }],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<EnrolledIn contactId="c1" me={aMe()} isPartner={false} />);
    expect(await screen.findByText(/Unsubscribed from marketing emails on 2026-09-28/))
      .toBeInTheDocument();
  });
});
