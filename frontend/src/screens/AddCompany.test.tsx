import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aCompany, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { AddCompany } from "./AddCompany";

function setup(role: "FF" | "VA" = "FF", overrides: Record<string, unknown> = {}) {
  const onDone = vi.fn();
  const fetchMock = mockApi({
    "POST /api/companies/": (body: unknown) => ({
      status: 201, body: { ...aCompany(), ...(body as object) },
    }),
    ...overrides,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<AddCompany me={aMe({ role })} onDone={onDone} />);
  return { onDone, fetchMock };
}

function postedBody(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
}

describe("AddCompany", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("sends the FR-1.3 fields", async () => {
    const user = userEvent.setup();
    const { fetchMock, onDone } = setup();

    await user.type(screen.getByLabelText("Name"), "Acme Holdings");
    await user.type(screen.getByLabelText("Industry"), "Manufacturing");
    await user.type(screen.getByLabelText("Email domains"), "acme.com, acme.co.uk");
    await user.type(screen.getByLabelText("Address"), "1 Main St\nDenver");
    await user.click(screen.getByRole("button", { name: "Save company" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(postedBody(fetchMock)).toMatchObject({
      name: "Acme Holdings",
      industry: "Manufacturing",
      domains: ["acme.com", "acme.co.uk"],
      address: { lines: ["1 Main St", "Denver"] },
    });
  });

  it("offers a seat count to an FF and sends it", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup("FF");

    await user.type(screen.getByLabelText("Name"), "Acme");
    await user.type(screen.getByLabelText("Client seat count"), "5");
    await user.click(screen.getByRole("button", { name: "Save company" }));

    await waitFor(() => expect(postedBody(fetchMock)).toBeTruthy());
    expect(postedBody(fetchMock).seat_count).toBe(5);
  });

  it("hides the seat count from a VA and never sends one", async () => {
    // Matrix 4.12 — seat_count is FF-only. The API refuses it too; this keeps
    // the VA from being shown a field that would only fail on save.
    const user = userEvent.setup();
    const { fetchMock } = setup("VA");

    expect(screen.queryByLabelText("Client seat count")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Save company" }));

    await waitFor(() => expect(postedBody(fetchMock)).toBeTruthy());
    expect(postedBody(fetchMock)).not.toHaveProperty("seat_count");
  });

  it("never offers to set the client flag by hand", async () => {
    setup();
    // FR-1.6a keeps one answer to "is this a client": the sales pipeline.
    expect(screen.queryByLabelText(/client company/i)).not.toBeInTheDocument();
    expect(screen.getByText(/derived when one of their contacts reaches/i))
      .toBeInTheDocument();
  });

  it("sends a null address when none is typed", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.type(screen.getByLabelText("Name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Save company" }));

    await waitFor(() => expect(postedBody(fetchMock)).toBeTruthy());
    expect(postedBody(fetchMock).address).toBeNull();
  });

  it("cannot be saved without a name", async () => {
    setup();
    expect(screen.getByRole("button", { name: "Save company" })).toBeDisabled();
  });

  it("surfaces the duplicate-name refusal from the API", async () => {
    const user = userEvent.setup();
    setup("FF", {
      "POST /api/companies/": () => ({
        status: 400,
        body: { name: ["“Acme Holdings” already exists. Open it instead of creating a second one."] },
      }),
    });

    await user.type(screen.getByLabelText("Name"), "Acme Holdings");
    await user.click(screen.getByRole("button", { name: "Save company" }));

    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
  });
});
