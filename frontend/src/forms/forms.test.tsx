/// <reference types="vite/client" />
/** The owner's intake form: white label at the source, its own bundle, and
 *  the behaviour an owner sees as they go. */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bathType, roomSummary } from "./derive";
import { FormApp } from "./FormApp";
import { Pending, PendingContext } from "./pending";
import { AccessSection, BathroomsSection, BedroomsSection, TaxSection } from "./sections";
import type { Answers, Brand, Ctx, OwnerForm, Secrets, SecretState } from "./types";

const sources = import.meta.glob(["./**/*.{ts,tsx,css,html}", "!./**/*.test.tsx"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;

const FORM: OwnerForm = {
  sections: [], options: {
    where: [{ value: "living", label: "Living room" }],
    door: [{ value: "smart_lock", label: "Wi-Fi smart lock" },
           { value: "keypad", label: "Keypad lock (not on Wi-Fi)" },
           { value: "lockbox", label: "Lockbox" }, { value: "key", label: "A key only" }],
    owner_closet: [{ value: "code", label: "Yes, it opens with a code" },
                   { value: "key", label: "Yes, it opens with a key" },
                   { value: "no", label: "No" }],
    alarm: [{ value: "code", label: "Yes, it's set with a code" },
            { value: "no_code", label: "Yes, but it has no code" }, { value: "no", label: "No" }],
    tax_kind: [{ value: "tax_id", label: "My business tax ID (EIN)" },
               { value: "ssn", label: "My Social Security number or ITIN" },
               { value: "phone", label: "I'd rather give it by phone" }],
    tax_phone_kind: [{ value: "tax_id", label: "Their business tax ID (EIN)" },
                     { value: "ssn", label: "Their Social Security number or ITIN" }],
  }, builtin: {},
  tax_wording: { why: "Mountain Stays needs this number once, to file your property's rental "
    + "permit.", how: "It's encrypted as soon as you save it." },
  bed_types: [{ id: 1, label: "King", sleeps: 2, other_places: false },
              { id: 3, label: "Queen", sleeps: 2, other_places: false },
              { id: 5, label: "Twin", sleeps: 1, other_places: false },
              { id: 7, label: "Queen Sofa Bed", sleeps: 2, other_places: true }],
  bathroom_fixtures: [{ id: 11, name: "Shower", kind: "shower" },
                      { id: 12, name: "Toilet", kind: "" }, { id: 13, name: "Bathtub", kind: "tub" },
                      { id: 14, name: "Sink", kind: "" }],
  common_amenities: [], amenity_groups: [], lodging_types: [],
  code_types: [{ id: 2, name: "Garage Code" }], trash_days: [], custom_fields: [],
};

const NONE: Secrets = { tax_id: null, wifi_password: false, codes: {} };

function fakeApi(refuse = "") {
  const held: Record<string, boolean> = {};
  return {
    saveSection: vi.fn(async () => {}),
    putSecret: vi.fn(async (_k: string, slot: string, _v: string): Promise<Secrets> => {
      if (refuse) throw new Error(refuse);
      held[slot] = true;
      return { ...NONE, codes: { ...held } };
    }),
    clearSecret: vi.fn(async (_k: string, slot: string): Promise<Secrets> => {
      delete held[slot];
      return { ...NONE, codes: { ...held } };
    }),
    uploadFile: vi.fn(), deleteFile: vi.fn(),
  };
}

function Harness({ Section, initial, api = fakeApi(), pending = new Pending(), mode = "owner",
  needs, markNone }: {
  Section: (p: { ctx: Ctx }) => ReactElement; initial: Answers;
  api?: ReturnType<typeof fakeApi>; pending?: Pending; mode?: "owner" | "staff";
  needs?: Record<string, SecretState>; markNone?: Ctx["markNone"];
}) {
  const [answers, setAnswers] = useState<Answers>(initial);
  const [secrets, setSecrets] = useState<Secrets>(NONE);
  const ctx: Ctx = { form: FORM, answers, update: (s, v) => setAnswers((a) => ({ ...a, [s]: v })),
                     secrets, setSecrets, files: [], setFiles: () => {}, api, brand: "Mountain Stays",
                     mode, needs, markNone };
  return <PendingContext.Provider value={pending}>
    <div className="ix-root"><Section ctx={ctx} /></div></PendingContext.Provider>;
}

describe("the owner's bundle", () => {
  it("names nobody but the form's own brand", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(6);
    const words = /execs ?now|executives now|noble rose|getexecutivesnow|practice owner/i;
    const found = Object.entries(sources).filter(([, text]) => words.test(text))
      .map(([file]) => file);
    expect(found).toEqual([]);
  });

  it("imports nothing from the rest of the app", () => {
    const outside = Object.entries(sources).flatMap(([file, text]) =>
      [...text.matchAll(/from\s+["']([^"']+)["']|import\s+["']([^"']+)["']/g)]
        .map((m) => m[1] ?? m[2])
        .filter((spec) => spec.startsWith("..") || spec.startsWith("/src"))
        .map((spec) => `${file}: ${spec}`));
    expect(outside).toEqual([]);
  });
});

describe("as the owner fills it in", () => {
  it("sums a bedroom up as it goes", () => {
    expect(roomSummary(FORM, "Bedroom 2", [{ type: 3, count: 1 }, { type: 5, count: 2 }]))
      .toBe("Bedroom 2: Queen x1, Twin x2, sleeps 4");
    render(<Harness Section={BedroomsSection} initial={{ bedrooms: [] }} />);
    fireEvent.click(screen.getByRole("button", { name: /Add a bedroom/ }));
    const bed = screen.getByRole("combobox", { name: "Bed 1 type" });
    fireEvent.change(bed, { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "One more: King" }));
    expect(screen.getByText("Bedroom 1: King x2, sleeps 4")).toBeInTheDocument();
  });

  it("works a bathroom's type out from what's in it", () => {
    expect(bathType(FORM, { "13": 1, "11": 1 })).toBe("Full bathroom");
    expect(bathType(FORM, { "11": 1, "14": 2 })).toBe("Three-quarter bathroom");
    expect(bathType(FORM, { "12": 1, "14": 1 })).toBe("Half bathroom");
    render(<Harness Section={BathroomsSection} initial={{ bathrooms: [{ fixtures: {} }] }} />);
    const block = screen.getByRole("region", { name: "Bathroom 1" });
    fireEvent.click(within(block).getByLabelText("Shower"));
    fireEvent.click(within(block).getByLabelText("Sink"));
    fireEvent.click(within(block).getByRole("button", { name: "One more: Sink" }));
    expect(within(block).getByText("Bathroom 1: Three-quarter bathroom (Shower, Sink x2)"))
      .toBeInTheDocument();
  });

  it("never shows a saved code again", async () => {
    render(<Harness Section={AccessSection} initial={{ access: { door: "smart_lock" } }} />);
    const box = screen.getByLabelText("Door code");
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "4821" } });
    fireEvent.blur(box);
    expect(await screen.findByText("Saved securely")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("4821")).toBeNull();
    expect(document.body.textContent).not.toContain("4821");
  });

  it("reads the token from either address", async () => {
    const { tokenFrom } = await import("./token");
    expect(tokenFrom("/forms/mountain-stays/abcdefghijklmnopqrstuvwxyz0123456789_-ABCD"))
      .toBe("abcdefghijklmnopqrstuvwxyz0123456789_-ABCD");
    expect(tokenFrom("/abcdefghijklmnopqrstuvwxyz0123456789_-ABCD/")).toBe(
      "abcdefghijklmnopqrstuvwxyz0123456789_-ABCD");
    expect(tokenFrom("/forms/mountain-stays")).toBeNull();
  });
});

// Owner, 2026-11-20: intake #1's door code was typed and never saved, because
// the field wanted its own Save. Sensitive values save like every answer.
describe("a sensitive value saves like every other answer", () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("has no Save button and saves a moment after the last key", async () => {
    vi.useFakeTimers();
    const api = fakeApi();
    render(<Harness Section={AccessSection} initial={{ access: { door: "keypad" } }} api={api} />);
    expect(screen.queryByRole("button", { name: /^Save/ })).toBeNull();
    const box = screen.getByLabelText("Door code");
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "48" } });
    fireEvent.change(box, { target: { value: "4821" } });
    expect(api.putSecret).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(api.putSecret).toHaveBeenCalledTimes(1);
    expect(api.putSecret).toHaveBeenCalledWith("code", "door", "4821");
    // Still typing in it: the box stays, and says it is saved.
    expect(screen.getByText("Saved securely")).toBeInTheDocument();
    expect(screen.getByLabelText("Door code")).toBeInTheDocument();
  });

  it("saves at once on leaving the field, then shows only Saved securely", async () => {
    vi.useFakeTimers();
    const api = fakeApi();
    render(<Harness Section={AccessSection} initial={{ access: { door: "keypad" } }} api={api} />);
    const box = screen.getByLabelText("Door code");
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "4821" } });
    fireEvent.blur(box);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });   // not the 700 ms
    expect(api.putSecret).toHaveBeenCalledWith("code", "door", "4821");
    expect(screen.getByText("Saved securely")).toBeInTheDocument();
    expect(screen.queryByLabelText("Door code")).toBeNull();
    expect(screen.getByRole("button", { name: "Change Door code" })).toBeInTheDocument();
  });

  it("is saved by Continue, Submit or Send before they move on", async () => {
    const api = fakeApi();
    const pending = new Pending();
    render(<Harness Section={AccessSection} initial={{ access: { door: "keypad" } }} api={api}
      pending={pending} />);
    fireEvent.change(screen.getByLabelText("Door code"), { target: { value: "4821" } });
    expect(pending.dirty()).toBe(true);
    let ok = false;
    await act(async () => { ok = await pending.flush(); });
    expect(ok).toBe(true);
    expect(api.putSecret).toHaveBeenCalledWith("code", "door", "4821");
    expect(pending.dirty()).toBe(false);
  });

  it("stops them, and says why beside the field, when it can't be saved", async () => {
    const api = fakeApi("A business tax ID (EIN) has 9 digits, like 12-3456789.");
    const pending = new Pending();
    render(<Harness Section={TaxSection} initial={{ tax: { kind: "tax_id" } }} api={api}
      pending={pending} />);
    fireEvent.change(screen.getByLabelText("Business tax ID (EIN)"),
                     { target: { value: "12-34" } });
    let ok = true;
    await act(async () => { ok = await pending.flush(); });
    expect(ok).toBe(false);
    expect(screen.getByRole("alert")).toHaveTextContent("has 9 digits");
    expect(screen.getByLabelText("Business tax ID (EIN)")).toHaveAttribute("aria-invalid", "true");
    expect(pending.dirty()).toBe(true);
  });

  it("asks which number goes on the rental permit, and says why and how (2026-11-24)", () => {
    render(<Harness Section={TaxSection} initial={{ tax: { kind: "ssn" } }} />);
    expect(screen.getByText("Which number should go on your rental permit?")).toBeInTheDocument();
    expect(screen.getByText(/needs this number once, to file your property's rental permit/))
      .toBeInTheDocument();
    expect(screen.getByText(/encrypted as soon as you save it/)).toBeInTheDocument();
    expect(screen.getByLabelText("Social Security number or ITIN")).toBeInTheDocument();
    expect(screen.queryByText(/you'll add it yourself in your owner portal/i)).toBeNull();
  });

  it("by phone: nothing for the owner to enter; staff say which and type it in", () => {
    const { unmount } = render(<Harness Section={TaxSection}
      initial={{ tax: { kind: "phone" } }} />);
    expect(screen.getByText(/We'll call you for it/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Social Security number or ITIN")).toBeNull();
    unmount();
    render(<Harness Section={TaxSection} mode="staff"
      initial={{ tax: { kind: "phone", phone_kind: "ssn" } }} />);
    expect(screen.getByText(/The owner asked to give it by phone/)).toBeInTheDocument();
    expect(screen.getByLabelText("Social Security number or ITIN")).toBeInTheDocument();
  });

  it("Continue on the owner's form waits for a code typed and nothing else pressed", async () => {
    const calls: string[] = [];
    let refuse = false;
    const page = {
      state: "open", number: 1, first_name: "Alex", missing: [], files: [],
      answers: { access: { door: "keypad" } }, secrets: NONE,
      form: { ...FORM, sections: [{ key: "welcome", title: "Welcome" },
                                  { key: "access", title: "Getting in" },
                                  { key: "stays", title: "Your own stays" }] },
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push(`${method} ${url}`);
      if (method === "POST" && url.endsWith("/secret")) {
        if (refuse) return new Response(JSON.stringify({ detail: "Try again." }),
                                        { status: 400 });
        return new Response(JSON.stringify({ secrets: { ...NONE, codes: { door: true } } }));
      }
      return new Response(JSON.stringify(method === "GET" ? page : {}));
    }));
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    window.location.hash = "#access";
    const brand: Brand = { brand_name: "Mountain Stays", title: "New owner", slug: "m",
                           colors: {}, contact_phone: "", contact_email: "", logo: "",
                           icon: "" };
    render(<FormApp brand={brand} token="t0ken" />);
    const box = await screen.findByLabelText("Door code");
    // The save is refused: Continue stays on the step and says so.
    refuse = true;
    fireEvent.change(box, { target: { value: "4821" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText(/isn't saved yet/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Getting in");
    // Saved: Continue moves on, only after the code reached the server.
    refuse = false;
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }))
      .toHaveTextContent("Your own stays"));
    expect(calls.filter((c) => c === "POST /api/f/t0ken/secret")).toHaveLength(2);
  });
});

describe("getting in", () => {
  it("asks for no code for a closet that opens with a key", () => {
    render(<Harness Section={AccessSection} initial={{ access: { door: "key" } }} />);
    expect(screen.queryByLabelText("Door code")).toBeNull();
    fireEvent.click(screen.getByLabelText("Yes, it opens with a key"));
    expect(screen.queryByLabelText("Owner's closet code")).toBeNull();
    expect(screen.getByText("If it opens with a key, there's no code to enter."))
      .toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Yes, it opens with a code"));
    expect(screen.getByLabelText("Owner's closet code")).toBeInTheDocument();
  });

  it("asks for an alarm code only for an alarm set with one", () => {
    render(<Harness Section={AccessSection} initial={{ access: { door: "key" } }} />);
    fireEvent.click(screen.getByLabelText("Yes, but it has no code"));
    expect(screen.queryByLabelText("Alarm code")).toBeNull();
    fireEvent.click(screen.getByLabelText("Yes, it's set with a code"));
    expect(screen.getByLabelText("Alarm code")).toBeInTheDocument();
  });

  it("reads a closet answered yes before the rewording as one with a code", () => {
    render(<Harness Section={AccessSection}
      initial={{ access: { door: "key", owner_closet: "yes", alarm: "yes" } }} />);
    expect(screen.getByLabelText("Yes, it opens with a code")).toBeChecked();
    expect(screen.getByLabelText("Owner's closet code")).toBeInTheDocument();
    expect(screen.getByLabelText("Alarm code")).toBeInTheDocument();
  });
});

describe("on the review screen", () => {
  it("shows a missing code beside its question, with both ways out", async () => {
    const markNone = vi.fn(async () => {});
    render(<Harness Section={AccessSection} mode="staff" markNone={markNone}
      initial={{ access: { door: "keypad", alarm: "code" } }}
      needs={{ "code:door": "missing", "code:alarm": "none" }} />);
    const door = document.querySelector('[data-needed="code:door"]')!;
    expect(door).toHaveTextContent("Needed before Send: the door code isn't in ENHQ.");
    expect(screen.getByLabelText("Door code")).toBeInTheDocument();      // enter it
    fireEvent.click(within(door as HTMLElement).getByRole("button",
      { name: "mark that there is none" }));
    await waitFor(() => expect(markNone).toHaveBeenCalledWith("code:door", true));
    const alarm = document.querySelector('[data-needed="code:alarm"]')!;
    expect(alarm).toHaveTextContent("Marked as having no alarm code: nothing is sent for it.");
    fireEvent.click(within(alarm as HTMLElement).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(markNone).toHaveBeenCalledWith("code:alarm", false));
  });

  it("shows nothing of the kind on the owner's form", () => {
    render(<Harness Section={AccessSection} initial={{ access: { door: "keypad" } }}
      needs={{ "code:door": "missing" }} markNone={vi.fn()} />);
    expect(document.querySelector("[data-needed]")).toBeNull();
  });
});
