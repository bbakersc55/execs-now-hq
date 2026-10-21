import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmailTemplate } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { EmailTemplates, TemplateUses } from "./EmailTemplates";

function template(overrides: Partial<EmailTemplate> = {}): EmailTemplate {
  return {
    id: "t1", name: "Referral thank-you: won", kind: "general",
    subject: "Good news, and thank you",
    body: "Hi {FirstName},\n\nGood news: {ProspectName} has decided to work with us.",
    first_name_fallback: "there", original: "thanks_won", is_original: true, changed: false,
    used_for: ["Thank-you when the prospect is won"], updated_at: "2026-10-20T12:00:00Z",
    ...overrides,
  };
}

const mine = template({ id: "t2", name: "Proposal nudge", original: "", is_original: false,
  subject: "Following up, {FirstName}", body: "Hi {FirstName},", used_for: [] });

/** Owner, 2026-10-20: one library, plain text with chips, built-in ones restorable. */
describe("Email templates", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists built-in and own templates and shows the body as chips", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/email-templates/": [template(), mine] }));
    renderRoute(<EmailTemplates />);
    const list = await screen.findByRole("list", { name: "Templates" });
    expect(within(list).getByText("Built-in")).toBeInTheDocument();
    expect(within(list).getByText("Not in use")).toBeInTheDocument();
    const body = screen.getByRole("textbox", { name: "Template body" });
    expect([...body.querySelectorAll<HTMLElement>("[data-merge]")].map((c) => c.dataset.merge))
      .toEqual(["{FirstName}", "{ProspectName}"]);
    expect(screen.getByText(/Used for:/).parentElement).toHaveTextContent(
      "Thank-you when the prospect is won");
    expect(screen.queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Restore the original/ })).toBeDisabled();
  });

  it("saves the words as plain text and restores a built-in one", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/email-templates/t1/restore/": template(),
      "PATCH /api/email-templates/t1/": template({ changed: true }),
      "GET /api/email-templates/": [template({ changed: true })],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<EmailTemplates />);
    const body = await screen.findByRole("textbox", { name: "Template body" });
    body.querySelector("p")!.append(" Cheers.");
    fireEvent.input(body);
    await user.clear(screen.getByLabelText("If a first name is missing, use"));
    await user.type(screen.getByLabelText("If a first name is missing, use"), "friend");
    await user.click(screen.getByRole("button", { name: /Save/ }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body).toEqual({
      body: "Hi {FirstName}, Cheers.\n\nGood news: {ProspectName} has decided to work with us.",
      first_name_fallback: "friend",
    }));
    await user.click(screen.getByRole("button", { name: /Restore the original/ }));
    await waitFor(() => expect(fetchMock.calls.some(
      (c) => c.method === "POST" && c.url.endsWith("/t1/restore/"))).toBe(true));
  });

  it("drops a merge field at the cursor from its button", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/email-templates/": [mine] }));
    renderRoute(<EmailTemplates />);
    const body = await screen.findByRole("textbox", { name: "Template body" });
    const range = document.createRange();
    range.selectNodeContents(body.querySelector("p")!);
    range.collapse(false);
    getSelection()!.removeAllRanges();
    getSelection()!.addRange(range);
    fireEvent.mouseDown(screen.getByRole("button", { name: "{Company}" }));
    expect([...body.querySelectorAll<HTMLElement>("[data-merge]")].map((c) => c.dataset.merge))
      .toEqual(["{FirstName}", "{Company}"]);
    expect(screen.getByRole("button", { name: /Delete/ })).toBeEnabled();
  });

  it("says why a save was refused", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "PATCH /api/email-templates/t2/": () => ({ status: 400, body: {
        body: ["There is no merge field called {Frist}."] } }),
      "GET /api/email-templates/": [mine],
    }));
    renderRoute(<EmailTemplates />);
    await user.type(await screen.findByRole("textbox", { name: "Subject" }), "!");
    await user.click(screen.getByRole("button", { name: /Save/ }));
    expect(await screen.findByText(/no merge field called \{Frist\}/)).toBeInTheDocument();
  });

  it("chooses which template each practice-wide email uses", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/email-templates/uses/": { uses: [
        { use: "thanks_won", label: "Thank-you when the prospect is won", template: "t2" }] },
      "GET /api/email-templates/uses/": { uses: [
        { use: "thanks_won", label: "Thank-you when the prospect is won", template: "t1" }] },
      "GET /api/email-templates/": [template(), mine],
    });
    vi.stubGlobal("fetch", fetchMock);
    const notes: string[] = [];
    renderRoute(<TemplateUses onNote={(text) => notes.push(text)} />);
    const pick = await screen.findByRole("combobox", { name: "Thank-you when the prospect is won" });
    await waitFor(() => expect(within(pick).getAllByRole("option")).toHaveLength(2));
    await user.selectOptions(pick, "t2");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ use: "thanks_won", template: "t2" }));
    await waitFor(() => expect(notes.at(-1)).toBe("Template chosen. New drafts use it."));
  });
});
