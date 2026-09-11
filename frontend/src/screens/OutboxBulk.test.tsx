import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { sanitize, toPlainText } from "../components/RichText";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Outbox } from "./Outbox";

function aMessage(overrides: Record<string, unknown> = {}) {
  return {
    id: "m1", state: "pending_approval", producer: "referral_touch",
    to_contact: null, to_address: "partner@example.invalid",
    from_address: "bryan@getexecutivesnow.com",
    subject: "Checking in", body_text: "Hello there", body_html: "",
    is_ai_generated: true, warning: "", send_by: "2026-10-01T00:00:00Z",
    approved_by: null, approved_at: null, sent_at: null, sent_via: "",
    dev_real_send: false, created_at: "2026-09-11T00:00:00Z",
    attachments: [],
    sender_options: [
      { value: "alias", address: "info@getexecutivesnow.com", label: "The practice alias" },
      { value: "self", address: "bryan@getexecutivesnow.com", label: "My own address" },
    ],
    delivery: { target: "dev", label: "Dev mailbox (Mailpit)", is_local_build: true },
    ...overrides,
  };
}

function setup(messages: unknown[], routes: Record<string, unknown> = {}, me = aMe()) {
  const fetchMock = mockApi({
    // Outbox reads its own role from /api/me rather than taking a prop.
    "/api/me": me,
    "/api/outbox/": messages,
    "POST /api/outbox/approve-selected/": { approved_count: 2, failed: [] },
    ...routes,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Outbox />);
  return fetchMock;
}

describe("Outbox attachments", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows every attachment with filename and size", async () => {
    // Check 5: the flyer WAS attached; the Outbox never rendered it.
    setup([aMessage({
      producer: "referral_onboarding",
      attachments: [{ id: "a1", filename: "Executives-Now.pdf",
                      byte_size: 404710, content_type: "application/pdf",
                      content_present: true }],
    })]);

    expect(await screen.findByText(/Executives-Now\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/395 KB/)).toBeInTheDocument();
  });

  it("flags an attachment whose bytes are missing", async () => {
    // The Check 5 state: a row recorded at full size with no file behind it.
    // Saying so here means it is caught before approval, not at send time.
    setup([aMessage({
      attachments: [{ id: "a1", filename: "Executives-Now.pdf", byte_size: 404710,
                      content_type: "application/pdf", content_present: false }],
    })]);

    expect(await screen.findByText(/file missing — re-upload before sending/))
      .toBeInTheDocument();
  });

  it("says nothing about attachments when there are none", async () => {
    setup([aMessage()]);
    await screen.findByText("Checking in");
    expect(screen.queryByText(/📎/)).not.toBeInTheDocument();
  });
});

describe("Outbox batch approval", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("selects all pending, deselects one, and approves the rest", async () => {
    const user = userEvent.setup();
    const fetchMock = setup([
      aMessage({ id: "m1", subject: "First" }),
      aMessage({ id: "m2", subject: "Second" }),
      aMessage({ id: "m3", subject: "Third" }),
    ]);

    await user.click(await screen.findByRole("button", { name: /Select all 3 shown/ }));
    await user.click(screen.getByLabelText("Select Second"));  // deselect one

    await user.click(screen.getByRole("button", { name: /Approve 2 selected/ }));

    await waitFor(() => {
      const post = fetchMock.calls.find((c) => c.url.includes("approve-selected"));
      expect(post?.body).toEqual({ ids: ["m1", "m3"] });
    });
  });

  it("says each one is still approved individually", async () => {
    setup([aMessage()]);
    expect(await screen.findByText(/still approved individually/)).toBeInTheDocument();
    expect(screen.getByText(/not a way around approval/)).toBeInTheDocument();
  });

  it("offers no batch approval to a VA", async () => {
    setup([aMessage()], {}, aMe({ role: "VA" }));

    await screen.findByText("Checking in");
    // Matrix 5.3 — a VA cannot approve, so there is nothing to batch.
    expect(screen.queryByRole("button", { name: /Select all/ })).not.toBeInTheDocument();
  });
});

describe("Review & edit", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("offers the verified send-as addresses and saves the override", async () => {
    const user = userEvent.setup();
    const fetchMock = setup([aMessage()], {
      "PATCH /api/outbox/m1/edit/": (b: unknown) => ({ status: 200, body: b }),
      "POST /api/outbox/m1/approve/": aMessage({ state: "sent" }),
    });

    await user.click(await screen.findByRole("button", { name: "Review & edit" }));
    await user.selectOptions(screen.getByLabelText("Send from"), "alias");
    await user.click(screen.getByRole("button", { name: /Approve & send/ }));

    await waitFor(() => {
      const patch = fetchMock.calls.find((c) => c.method === "PATCH");
      expect(patch?.body).toMatchObject({ sender: "alias" });
    });
  });

  it("saves edits before approving, so what was read is what is sent", async () => {
    const user = userEvent.setup();
    const fetchMock = setup([aMessage()], {
      "PATCH /api/outbox/m1/edit/": (b: unknown) => ({ status: 200, body: b }),
      "POST /api/outbox/m1/approve/": aMessage({ state: "sent" }),
    });

    await user.click(await screen.findByRole("button", { name: "Review & edit" }));
    await user.clear(screen.getByLabelText("Subject"));
    await user.type(screen.getByLabelText("Subject"), "Rewritten subject");
    await user.click(screen.getByRole("button", { name: /Approve & send/ }));

    await waitFor(() => {
      const calls = fetchMock.calls.map((c) => `${c.method} ${c.url}`);
      const patchAt = calls.findIndex((c) => c.startsWith("PATCH"));
      const approveAt = calls.findIndex((c) => c.includes("/approve/"));
      expect(patchAt).toBeGreaterThan(-1);
      expect(patchAt).toBeLessThan(approveAt);
    });
  });
});

describe("RichText output", () => {
  it("keeps the formatting an email needs", () => {
    expect(sanitize("<p>Hi <b>Dana</b></p>")).toBe("<p>Hi <b>Dana</b></p>");
    expect(sanitize('<p><a href="https://x.invalid">link</a></p>'))
      .toBe('<p><a href="https://x.invalid">link</a></p>');
  });

  it("strips the style soup a paste from Word brings", () => {
    expect(sanitize('<p><span style="font-family:Calibri">Hi</span></p>'))
      .toBe("<p>Hi</p>");
    expect(sanitize('<div class="x"><script>alert(1)</script>Hi</div>'))
      .toBe("alert(1)Hi");
  });

  it("drops a javascript: href but keeps the text", () => {
    expect(sanitize('<a href="javascript:alert(1)">click</a>'))
      .toBe("<a>click</a>");
  });

  it("produces a plain-text alternative", () => {
    expect(toPlainText("<p>Hi Dana</p><p>Line two<br>Line three</p>"))
      .toBe("Hi Dana\n\nLine two\nLine three");
  });
});
