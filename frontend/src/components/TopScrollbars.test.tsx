import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { syncTopScrollbars } from "./TopScrollbars";

/** jsdom lays nothing out, so a box's widths are given by hand. */
function box(html: string, { scroll = 900, client = 360 } = {}) {
  document.body.innerHTML = `<main>${html}</main>`;
  const el = document.querySelector<HTMLElement>("main table")!;
  Object.defineProperty(el, "scrollWidth", { configurable: true, value: scroll });
  Object.defineProperty(el, "clientWidth", { configurable: true, value: client });
  return el;
}

function phone(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches, media: query,
    addEventListener: () => {}, removeEventListener: () => {} }));
}

describe("a wide table's scrollbar at the top of its box (Bryan, 2026-10-24)", () => {
  beforeEach(() => phone(true));
  afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

  it("draws a bar above a table that scrolls sideways at phone width, following its scroll", () => {
    const table = box('<div class="card"><table style="overflow-x: auto"><tr><td>wide</td></tr></table></div>');
    syncTopScrollbars();
    const bar = table.previousElementSibling as HTMLElement;
    expect(bar.className).toBe("top-scroll");
    expect(bar.getAttribute("aria-hidden")).toBe("true");
    expect(bar.textContent).toContain("More columns");
    const thumb = bar.querySelector<HTMLElement>(".top-scroll-thumb")!;
    expect(thumb.style.width).toBe("144px");                    // 360 of 900, of a 360 track
    table.scrollLeft = 540;                                       // the far end
    table.dispatchEvent(new Event("scroll"));
    expect(thumb.style.transform).toBe("translateX(216px)");
    expect(bar.classList.contains("at-end")).toBe(true);
    // Run again: still one bar.
    syncTopScrollbars();
    expect(document.querySelectorAll(".top-scroll")).toHaveLength(1);
  });

  it("draws none for a table that fits, one shown as cards, or a wide screen", () => {
    box('<table style="overflow-x: auto"><tr><td>a</td></tr></table>', { scroll: 300, client: 360 });
    syncTopScrollbars();
    expect(document.querySelector(".top-scroll")).toBeNull();
    box('<table class="cards-on-phone" style="overflow-x: auto"><tr><td>a</td></tr></table>');
    syncTopScrollbars();
    expect(document.querySelector(".top-scroll")).toBeNull();
    phone(false);
    box('<table style="overflow-x: auto"><tr><td>a</td></tr></table>');
    syncTopScrollbars();
    expect(document.querySelector(".top-scroll")).toBeNull();
  });

  it("takes a bar away when its table no longer scrolls", () => {
    const table = box('<table style="overflow-x: auto"><tr><td>a</td></tr></table>');
    syncTopScrollbars();
    expect(document.querySelector(".top-scroll")).not.toBeNull();
    Object.defineProperty(table, "scrollWidth", { configurable: true, value: 300 });
    syncTopScrollbars();
    expect(document.querySelector(".top-scroll")).toBeNull();
  });
});
