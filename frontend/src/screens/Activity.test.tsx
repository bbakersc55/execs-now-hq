import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Activity } from "./Activity";

const ENTRIES = [
  { id: "c-1", at: "2026-09-15T15:00:00Z", source: "comment", kind: "comment",
    text: "commented on “Fix the loading dock”: Posted while acting.",
    entity: { type: "task", id: "t1", title: "Fix the loading dock" },
    by: "Bryan Baker", on_behalf_of: "Priya Shah" },
  { id: "u-1", at: "2026-09-15T14:00:00Z", source: "update", kind: "status_changed",
    text: "changed “Fix the loading dock” from Not started to In progress",
    entity: { type: "task", id: "t1", title: "Fix the loading dock" },
    by: "Dana Reyes", on_behalf_of: null },
  { id: "a-1", at: "2026-09-15T13:00:00Z", source: "event", kind: "portal.access_granted",
    text: "gave Ola New access to the portal", entity: null,
    by: "Bryan Baker", on_behalf_of: null },
];

describe("the portal activity log (FR-3.41)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists the company's history, saying who acted on whose behalf", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/portal-activity/": ENTRIES }));
    renderRoute(<Activity me={aMe({ role: "ECC", client_company: "co1" })} />);

    const acted = await screen.findByText(/Posted while acting\./);
    expect(acted.closest("li")).toHaveTextContent("Bryan Baker on behalf of Priya Shah");
    const plain = screen.getByText(/from Not started to In progress/).closest("li")!;
    expect(plain).toHaveTextContent("Dana Reyes changed");
    expect(plain).not.toHaveTextContent("on behalf of");
    expect(screen.getByText(/gave Ola New access to the portal/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "open" })[0]).toHaveAttribute("href", "/tasks/t1");
    expect(screen.getByText(/Nobody can edit or remove an entry/)).toBeInTheDocument();
  });

  it("offers no control that could change an entry", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/portal-activity/": ENTRIES }));
    renderRoute(<Activity me={aMe({ role: "FCC", client_company: "co1" })} />);
    await screen.findByText(/Posted while acting\./);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("asks nothing of the server for the practice, who are refused it", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Activity me={aMe()} />);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
