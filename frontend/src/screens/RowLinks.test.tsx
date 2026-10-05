import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aCompany, aContact, aMe } from "../test/fixtures";
import { mockApi } from "../test/render";
import { Companies } from "./Companies";
import { Contacts } from "./Contacts";

const DANA = aContact({
  id: "c1", first_name: "Dana", last_name: "Reyes", title: "COO",
  emails: [{ id: "e1", address: "dana@acme.invalid", is_primary: true }],
});

/** The list at its own path, and a stand-in for where a row leads. */
function show(path: string, list: ReactNode) {
  render(
    <QueryClientProvider client={new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={path} element={list} />
          <Route path={`${path}/:id`} element={<p>The record</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function showContacts() {
  vi.stubGlobal("fetch", mockApi({
    "GET /api/contacts/": [DANA],
    "GET /api/contact-types/": [],
    "GET /api/pipelines/": [],
  }));
  show("/contacts", <Contacts me={aMe()} />);
}

function showCompanies() {
  vi.stubGlobal("fetch", mockApi({
    "GET /api/companies/": [aCompany({ id: "co1", name: "Acme Facilities" })],
  }));
  show("/companies", <Companies me={aMe()} />);
}

/**
 * Rows that open their record (owner, 2026-10-05): the whole row is the
 * target, the name is still a link, and a control in the row stays a control.
 */
describe("a row opens its record", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("opens the contact from anywhere on the row", async () => {
    const user = userEvent.setup();
    showContacts();

    await user.click(await screen.findByText("COO"));

    expect(await screen.findByText("The record")).toBeInTheDocument();
  });

  it("keeps the contact's name a real link, without the underline", async () => {
    showContacts();
    const name = await screen.findByRole("link", { name: "Dana Reyes" });

    expect(name).toHaveAttribute("href", "/contacts/c1");
    expect(name).toHaveClass("rowname");
    expect(name.closest("tr")).toHaveClass("rowlink");
  });

  it("leaves the checkbox and Peek doing what they did", async () => {
    const user = userEvent.setup();
    showContacts();

    const box = await screen.findByRole("checkbox", { name: "Select Dana Reyes" });
    await user.click(box);
    expect(box).toBeChecked();
    expect(screen.queryByText("The record")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Peek at Dana Reyes" }));
    expect(await screen.findByRole("dialog", { name: "Contact" })).toBeInTheDocument();
    expect(screen.queryByText("The record")).not.toBeInTheDocument();
  });

  it("opens a new tab on Ctrl+click and on middle-click, and stays on the list", async () => {
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    showContacts();
    const cell = await screen.findByText("COO");

    fireEvent.click(cell, { ctrlKey: true });
    fireEvent(cell, new MouseEvent("auxclick", { bubbles: true, button: 1 }));

    expect(opened.mock.calls.map((call) => call[0])).toEqual(["/contacts/c1", "/contacts/c1"]);
    expect(screen.queryByText("The record")).not.toBeInTheDocument();
  });

  it("does not open the record when text in the row is being selected", async () => {
    const user = userEvent.setup();
    showContacts();
    const cell = await screen.findByText("dana@acme.invalid");
    vi.spyOn(window, "getSelection")
      .mockReturnValue({ toString: () => "dana@acme.invalid" } as Selection);

    await user.click(cell);

    expect(screen.queryByText("The record")).not.toBeInTheDocument();
  });

  it("opens the company from anywhere on the row, and not from Peek", async () => {
    const user = userEvent.setup();
    showCompanies();
    const name = await screen.findByRole("link", { name: "Acme Facilities" });
    expect(name).toHaveClass("rowname");
    const row = name.closest("tr") as HTMLElement;

    await user.click(within(row).getByRole("button", { name: "Peek at Acme Facilities" }));
    expect(await screen.findByRole("dialog", { name: "Company" })).toBeInTheDocument();
    expect(screen.queryByText("The record")).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(within(row).getAllByRole("cell")[1]);
    expect(await screen.findByText("The record")).toBeInTheDocument();
  });
});
