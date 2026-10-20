import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ImportDoor, importChoices } from "./ImportDoor";

describe("the Import door (U2)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("asks what is being imported and lists each importer with what it takes", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/me": aMe({ modules: ["personal"] }) }));
    renderRoute(<ImportDoor />);
    const list = await screen.findByRole("list", { name: "What are you importing?" });
    const links = within(list).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/import/contacts", "/finance/import", "/finance/personal/import", "/meetings"]);
    expect(within(list).getByRole("link", { name: /A business bank or card statement/ }))
      .toHaveTextContent("CSV, OFX, QFX, QBO or PDF");
    expect(within(list).getByRole("link", { name: /Contacts and companies/ }))
      .toHaveTextContent("A CSV");
  });

  it("offers the personal statement only with Personal finance, to the owner, not acting", () => {
    const keys = (me: Parameters<typeof importChoices>[0]) => importChoices(me).map((c) => c.key);
    expect(keys(aMe())).toEqual(["contacts", "business", "meetings"]);
    expect(keys(aMe({ modules: ["personal"] }))).toContain("personal");
    expect(keys(aMe({ modules: ["personal"], acting: {} as never }))).not.toContain("personal");
  });

  it("gives an assistant the contacts import only, and an associate nothing", () => {
    expect(importChoices(aMe({ role: "VA", modules: ["personal"] })).map((c) => c.key))
      .toEqual(["contacts"]);
    expect(importChoices(aMe({ role: "CF" }))).toEqual([]);
  });
});
