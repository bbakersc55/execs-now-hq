import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { renderRoute } from "../test/render";
import { StakeholdersPanel } from "./StakeholdersPanel";

const TASK = "t1";

type Person = { contact: string; name: string; email: string; company_name: string;
                is_practice: boolean };
const p = (contact: string, name: string, over: Partial<Person> = {}): Person => ({
  contact, name, email: "", company_name: "", is_practice: false, ...over,
});

/** A fetch stub that answers the candidates URL by what it asks for. */
function stub({ company = "Acme Facilities", inside = [] as Person[],
                outside = [] as Person[], attached = [] as { id: string; name: string }[] } = {}) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input.toString();
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    let payload: unknown = [];
    if (url.startsWith("/api/stakeholders/candidates/")) {
      const isOutside = url.includes("outside=1");
      const q = new URL(url, "http://x").searchParams.get("q") ?? "";
      const pool = isOutside || !company ? outside : inside;
      payload = {
        company: company ? "co1" : null, company_name: company ?? "", outside: isOutside,
        people: (isOutside || !company) && q.length < 2 ? []
          : pool.filter((x) => !q || x.name.toLowerCase().includes(q.toLowerCase())),
      };
    } else if (url.startsWith("/api/stakeholders/") && method === "GET") {
      payload = attached.map((a, i) => ({
        id: `s${i}`, contact: a, cadence: "weekly", is_muted: false, level: "task",
        attached_to: TASK, effective: true, last_notified_at: null,
      }));
    } else if (method === "POST") {
      payload = { id: "s9" };
    }
    return { ok: true, status: 200, statusText: "OK",
             text: async () => JSON.stringify(payload) } as Response;
  }));
  return calls;
}

describe("Who hears about this: the picker's scope", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("offers the client company's people with nothing typed, and adds one", async () => {
    const user = userEvent.setup();
    const calls = stub({ inside: [p("c1", "Dana Reyes"), p("c2", "Ben Orji")] });
    renderRoute(<StakeholdersPanel me={aMe()} target="task" id={TASK} />);

    expect(await screen.findByText("Dana Reyes")).toBeInTheDocument();
    expect(screen.getByText("Ben Orji")).toBeInTheDocument();
    expect(screen.getByLabelText("Narrow Acme Facilities's people")).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/api/contacts/search/"))).toBe(false);

    await user.click(screen.getByRole("button", { name: "Add Dana Reyes" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body)
      .toEqual({ contact: "c1", task: TASK }));
  });

  it("reaches someone outside the company only by choosing to, and by typing", async () => {
    const user = userEvent.setup();
    const calls = stub({
      inside: [p("c1", "Dana Reyes")],
      outside: [p("c7", "Boris Board", { company_name: "" }),
                p("c8", "Priya Shah", { company_name: "Northwind Foods" })],
    });
    renderRoute(<StakeholdersPanel me={aMe()} target="task" id={TASK} />);

    await user.click(await screen.findByLabelText("Someone outside Acme Facilities"));
    expect(await screen.findByText("Type at least two letters of their name.")).toBeInTheDocument();
    expect(screen.queryByText("Dana Reyes")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Find a contact to add"), "Pri");
    expect(await screen.findByText("Priya Shah")).toBeInTheDocument();
    expect(screen.getByText(/Northwind Foods/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("outside=1") && c.url.includes("q=Pri"))).toBe(true);
  });

  it("labels tenant staff as the practice", async () => {
    stub({ inside: [p("c1", "Dana Reyes")],
           outside: [p("c5", "Bryan Baker", { is_practice: true })] });
    const user = userEvent.setup();
    renderRoute(<StakeholdersPanel me={aMe()} target="task" id={TASK} />);
    await user.click(await screen.findByLabelText("Someone outside Acme Facilities"));
    await user.type(screen.getByLabelText("Find a contact to add"), "Bry");
    expect(await screen.findByRole("button", { name: "Add Bryan Baker (practice)" }))
      .toBeInTheDocument();
    expect(screen.getByText("(practice)")).toBeInTheDocument();
  });

  it("searches anyone for internal work, with no outside switch", async () => {
    const user = userEvent.setup();
    stub({ company: "", outside: [p("c8", "Priya Shah", { company_name: "Northwind Foods" })] });
    renderRoute(<StakeholdersPanel me={aMe()} target="task" id={TASK} />);
    expect(await screen.findByText("Type at least two letters of their name.")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Someone outside/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Find a contact to add"), "Pr");
    expect(await screen.findByText("Priya Shah")).toBeInTheDocument();
  });

  it("does not offer someone already attached", async () => {
    stub({ inside: [p("c1", "Dana Reyes"), p("c2", "Ben Orji")],
           attached: [{ id: "c1", name: "Dana Reyes" }] });
    renderRoute(<StakeholdersPanel me={aMe()} target="task" id={TASK} />);
    expect(await screen.findByRole("button", { name: "Add Ben Orji" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add Dana Reyes" })).not.toBeInTheDocument();
  });

  it("offers a client user no picker and asks the server for no candidates", async () => {
    const calls = stub({ inside: [p("c1", "Dana Reyes")] });
    renderRoute(<StakeholdersPanel me={aMe({ role: "ECC", client_company: "co1" })}
      target="task" id={TASK} />);
    expect(await screen.findByText("Nobody yet.")).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("candidates"))).toBe(false);
    expect(screen.queryByRole("button", { name: /^Add / })).not.toBeInTheDocument();
  });
});
