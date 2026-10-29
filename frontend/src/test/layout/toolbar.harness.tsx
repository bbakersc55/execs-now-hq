import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ReactDOM from "react-dom/client";
import { MemoryRouter } from "react-router-dom";

import { SectionRail } from "../../screens/SessionDetail";
import { Tasks } from "../../screens/Tasks";
import { aMe, COMPANY_ID } from "../fixtures";
import "../../theme.css";

/**
 * The strategy session's agenda rail and the client portal's Tasks toolbar in
 * a real browser, for `toolbarLayout.test.js` (owner, 2026-10-29): a long step
 * label ran under its minutes, and Mine / My team / Everyone stacked. Talks to
 * no server, and writes what it measured into `#layout` as JSON.
 */

const section = (code: string, title: string, minutes: number | null) => ({
  code, title, position: 0, time_budget_minutes: minutes, questions: [] });
const SECTIONS = [
  section("snapshot", "Snapshot", 10),
  section("diagnostic", "Diagnostic: where it's breaking", 25),
  section("mirror", "The mirror and where they want to go", 5),
  section("strategy_map", "Strategy Map", 15),
];

const me = aMe({ role: "FCC", client_company: COMPANY_ID, email: "ben@adapt.invalid",
  portal: { level_label: "Manager", may_create: { task: true, project: false, goal: false },
            edits_goals: false, has_teams_view: true, teams: [], may_propose_goal: false } });

window.fetch = async () => new Response("[]", {
  status: 200, headers: { "Content-Type": "application/json" } });

// Headless Chrome makes no window narrower than 500, so the page measures
// itself inside a frame of the width asked for (`?w=390`), which is then its
// viewport, media queries and all.
const asked = new URLSearchParams(location.search).get("w");
if (asked) {
  const frame = document.createElement("iframe");
  frame.src = location.pathname;
  frame.style.cssText = `width:${asked}px;height:1600px;border:0;display:block`;
  document.body.appendChild(frame);
  const copy = window.setInterval(() => {
    const done = frame.contentDocument?.getElementById("layout")?.textContent;
    if (!done) return;
    window.clearInterval(copy);
    document.getElementById("layout")!.textContent = done;
  }, 50);
} else {
  render();
}

function render() {
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
ReactDOM.createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={client}>
    <MemoryRouter>
      <main style={{ padding: 16 }}>
        <div className="session-layout" id="session">
          <SectionRail data={{ sections: SECTIONS, current_section: "diagnostic" } as never}
            onSection={7} onPick={() => undefined} />
          <div id="panel" style={{ minHeight: 200, background: "#eee" }}>The panel</div>
        </div>
        <section id="tasks"><Tasks me={me} /></section>
      </main>
    </MemoryRouter>
  </QueryClientProvider>,
);
}

const round = (n: number) => Math.round(n * 100) / 100;
const box = (el: Element | null) => {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: round(r.left), y: round(r.top), w: round(r.width), h: round(r.height),
           right: round(r.right), bottom: round(r.bottom) };
};

function measure() {
  const rail = Array.from(document.querySelectorAll(".rail button")).map((button) => ({
    label: button.firstElementChild?.textContent ?? "",
    button: box(button), text: box(button.firstElementChild),
    mins: box(button.querySelector(".mins")),
    lineHeight: parseFloat(getComputedStyle(button.firstElementChild!).lineHeight),
  }));
  const rows = Array.from(document.querySelectorAll("#tasks .filters-row"));
  const group = (name: string) => {
    const el = document.querySelector(`#tasks [role="group"][aria-label="${name}"]`);
    return el && { box: box(el),
                   buttons: Array.from(el.querySelectorAll("button")).map((b) => box(b)) };
  };
  return {
    width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth,
    rail, nav: box(document.querySelector(".rail")), panel: box(document.getElementById("panel")),
    rows: rows.map((row) => box(row)),
    search: box(rows[0]?.querySelector(".search") ?? null),
    whose: group("Whose work"), view: group("View"),
    firstRow: rows[0] ? Array.from(rows[0].children).map((c) => c.className || c.tagName) : [],
    selects: rows[1] ? Array.from(rows[1].querySelectorAll("select"))
      .map((s) => ({ label: s.getAttribute("aria-label"), ...box(s)! })) : [],
  };
}

const started = Date.now();
const timer = asked ? 0 : window.setInterval(async () => {
  const ready = document.querySelectorAll("#tasks .filters-row").length === 2
    && document.querySelectorAll(".rail button").length === SECTIONS.length;
  if (!ready && Date.now() - started < 8000) return;
  window.clearInterval(timer);
  await document.fonts.ready;
  document.getElementById("layout")!.textContent = JSON.stringify(
    ready ? measure() : { error: "the rail or the toolbar did not render" });
}, 50);
