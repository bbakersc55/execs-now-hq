import { useEffect } from "react";

/**
 * A wide table's scrollbar at the top of its box as well (Bryan, 2026-10-24):
 * at phone width a table that scrolls sideways in its own box showed its
 * scrollbar only at its foot, out of reach until the whole table had been
 * scrolled past. Phones hide native scrollbars until a box moves, so this one
 * is drawn: a track and a thumb above the box, with "More columns", that the
 * thumb's position mirrors and that can be dragged or tapped. The box itself
 * still scrolls by touch and keyboard; the bar is a pointer aid, hidden from
 * screen readers.
 *
 * One instance in the shell looks after every table in `main`, as they come
 * and go, so no screen has to remember it. Tables shown as cards at phone
 * width (`cards-on-phone`) don't scroll and get none.
 */

const PHONE = "(max-width: 700px)";
const BOXES = "main table, main .sc-scroll, main .sc-feed-grid, main .table-fit";

const bars = new WeakMap<HTMLElement, HTMLDivElement>();
const watched = new WeakSet<HTMLElement>();

function scrollsSideways(box: HTMLElement): boolean {
  if (box.matches("table.cards-on-phone")) return false;
  const overflow = getComputedStyle(box).overflowX;
  return (overflow === "auto" || overflow === "scroll") && box.scrollWidth > box.clientWidth + 1;
}

function place(box: HTMLElement, bar: HTMLDivElement) {
  const track = bar.querySelector<HTMLDivElement>(".top-scroll-track")!;
  const thumb = track.firstElementChild as HTMLDivElement;
  const width = track.clientWidth || box.clientWidth;
  const share = box.clientWidth / box.scrollWidth;
  const thumbWidth = Math.max(32, Math.round(width * share));
  const room = box.scrollWidth - box.clientWidth;
  thumb.style.width = `${thumbWidth}px`;
  thumb.style.transform = `translateX(${room > 0 ? Math.round((box.scrollLeft / room) * (width - thumbWidth)) : 0}px)`;
  bar.classList.toggle("at-end", box.scrollLeft >= room - 1);
}

function make(box: HTMLElement): HTMLDivElement {
  const bar = document.createElement("div");
  bar.className = "top-scroll";
  bar.setAttribute("aria-hidden", "true");
  bar.innerHTML = '<div class="top-scroll-track"><div class="top-scroll-thumb"></div></div>'
    + '<span class="top-scroll-hint">More columns →</span>';
  const track = bar.firstElementChild as HTMLDivElement;
  const thumb = track.firstElementChild as HTMLDivElement;
  // Where on the track a pointer is, as a scroll position of the box.
  const scrollFor = (clientX: number, grab: number) => {
    const rect = track.getBoundingClientRect();
    const room = rect.width - thumb.offsetWidth;
    const at = Math.min(Math.max(clientX - rect.left - grab, 0), Math.max(room, 0));
    return room > 0 ? (at / room) * (box.scrollWidth - box.clientWidth) : 0;
  };
  track.addEventListener("pointerdown", (e) => {
    const onThumb = e.target === thumb;
    const grab = onThumb ? e.clientX - thumb.getBoundingClientRect().left : thumb.offsetWidth / 2;
    box.scrollLeft = scrollFor(e.clientX, grab);
    track.setPointerCapture?.(e.pointerId);
    const move = (m: PointerEvent) => { box.scrollLeft = scrollFor(m.clientX, grab); };
    const up = () => {
      track.removeEventListener("pointermove", move);
      track.removeEventListener("pointerup", up);
      track.removeEventListener("pointercancel", up);
    };
    track.addEventListener("pointermove", move);
    track.addEventListener("pointerup", up);
    track.addEventListener("pointercancel", up);
    e.preventDefault();
  });
  return bar;
}

/** Add, size or take away the bar of every scrolling box under `main`. */
export function syncTopScrollbars() {
  const phone = typeof window.matchMedia === "function" && window.matchMedia(PHONE).matches;
  document.querySelectorAll<HTMLElement>(BOXES).forEach((box) => {
    let bar = bars.get(box);
    if (!phone || !scrollsSideways(box)) {
      if (bar) { bar.remove(); bars.delete(box); }
      return;
    }
    if (!bar || bar.nextElementSibling !== box) {
      bar?.remove();
      bar = make(box);
      box.parentNode?.insertBefore(bar, box);
      bars.set(box, bar);
    }
    if (!watched.has(box)) {
      watched.add(box);
      box.addEventListener("scroll", () => { const b = bars.get(box); if (b) place(box, b); },
        { passive: true });
    }
    place(box, bar);
  });
  // A bar whose box has gone, or moved, goes too.
  document.querySelectorAll<HTMLDivElement>("main .top-scroll").forEach((bar) => {
    const next = bar.nextElementSibling as HTMLElement | null;
    if (!next || bars.get(next) !== bar) bar.remove();
  });
}

export function TopScrollbars() {
  useEffect(() => {
    let frame = 0;
    const soon = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(syncTopScrollbars);
    };
    const main = document.querySelector("main");
    const seen = new MutationObserver((records) => {
      // Our own bars coming and going are not news.
      if (records.every((r) => [...r.addedNodes, ...r.removedNodes].every(
        (n) => n instanceof HTMLElement && n.classList.contains("top-scroll")))) return;
      soon();
    });
    if (main) seen.observe(main, { childList: true, subtree: true });
    window.addEventListener("resize", soon);
    soon();
    return () => {
      seen.disconnect();
      window.removeEventListener("resize", soon);
      cancelAnimationFrame(frame);
      document.querySelectorAll("main .top-scroll").forEach((bar) => bar.remove());
    };
  }, []);
  return null;
}
