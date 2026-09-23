import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { CallNotes } from "./CallNotes";

const CALL = {
  id: "m1", date: "2026-09-20", title: "Acme operations review",
  summary: "Dispatch and margin reporting came up, and two things were agreed.",
  client_company: "co1",
  others: [{ contact: "c2", name: "Priya Shah", is_practice: false }],
  practice: ["Bryan Baker"],
  source_link: "https://docs.google.com/document/d/abc",
  source_name: "Acme notes",
};

function show(rows: unknown[] = [CALL], me = aMe(),
              props: { contact?: string; company?: string } = { contact: "c1" }) {
  const fetchMock = mockApi({ "GET /api/meetings/": rows });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<CallNotes me={me} {...props} />);
  return fetchMock;
}

/**
 * The finding: the Meeting record existed on the timeline, but there was
 * nowhere to *read* what was said. This is that place.
 */
describe("call notes", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows each call with its summary, the others there, and the source", async () => {
    show();

    expect(await screen.findByText("Acme operations review")).toBeInTheDocument();
    expect(screen.getByText("2026-09-20")).toBeInTheDocument();
    expect(screen.getByText(/Dispatch and margin reporting/)).toBeInTheDocument();
    expect(screen.getByText(/with Priya Shah/)).toBeInTheDocument();
    expect(screen.getByText(/for the practice: Bryan Baker/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Acme notes/ }))
      .toHaveAttribute("href", "https://docs.google.com/document/d/abc");
  });

  it("says so rather than inventing one when the summary was discarded", async () => {
    show([{ ...CALL, summary: "" }]);

    expect(await screen.findByText(/No summary was kept for this call/))
      .toBeInTheDocument();
  });

  it("asks for one contact's calls, or one company's", async () => {
    const fetchMock = show([CALL], aMe(), { company: "co1" });

    expect(await screen.findByText("Acme operations review")).toBeInTheDocument();
    expect(fetchMock.calls[0].url).toContain("company=co1");
  });

  it("is not rendered for a client user, and asks for nothing", async () => {
    const fetchMock = show([CALL], aMe({ role: "FCC" }));

    expect(screen.queryByText("Call notes")).not.toBeInTheDocument();
    expect(fetchMock.calls).toHaveLength(0);
  });

  it("says plainly when there are none", async () => {
    show([]);

    expect(await screen.findByText(/No calls yet/)).toBeInTheDocument();
  });
});
