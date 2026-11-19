/// <reference types="vite/client" />
/** The owner's intake form: white label at the source, its own bundle, and
 *  the behaviour an owner sees as they go. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState, type ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { bathType, roomSummary } from "./derive";
import { AccessSection, BathroomsSection, BedroomsSection } from "./sections";
import type { Answers, Ctx, OwnerForm, Secrets } from "./types";

const sources = import.meta.glob(["./**/*.{ts,tsx,css,html}", "!./**/*.test.tsx"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;

const FORM: OwnerForm = {
  sections: [], options: { where: [{ value: "living", label: "Living room" }] }, builtin: {},
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

function Harness({ Section, initial }: { Section: (p: { ctx: Ctx }) => ReactElement;
  initial: Answers }) {
  const [answers, setAnswers] = useState<Answers>(initial);
  const [secrets, setSecrets] = useState<Secrets>({ tax_id: null, wifi_password: false,
                                                   codes: {} });
  const api = {
    saveSection: vi.fn(async () => {}),
    putSecret: vi.fn(async (_k: string, slot: string) => ({ tax_id: null, wifi_password: false,
                                                           codes: { [slot]: true } })),
    clearSecret: vi.fn(async () => ({ tax_id: null, wifi_password: false, codes: {} })),
    uploadFile: vi.fn(), deleteFile: vi.fn(),
  };
  const ctx: Ctx = { form: FORM, answers, update: (s, v) => setAnswers((a) => ({ ...a, [s]: v })),
                     secrets, setSecrets, files: [], setFiles: () => {}, api, brand: "Mountain Stays",
                     mode: "owner" };
  return <div className="ix-root"><Section ctx={ctx} /></div>;
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
    fireEvent.change(screen.getByLabelText("Door code"), { target: { value: "4821" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
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
