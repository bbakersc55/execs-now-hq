import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ReactDOM from "react-dom/client";
import { MemoryRouter } from "react-router-dom";

import { FinanceCategories } from "../../components/FinanceCategories";
import { FinanceCategory } from "../../lib/api";
import "../../theme.css";

/**
 * The chart of categories in a real browser, for `categoriesLayout.test.js`:
 * whether a label fits inside its button can only be measured where things
 * are laid out. It talks to no server, and writes what it measured into
 * `#layout` as JSON.
 */

const cat = (id: string, name: string, type: FinanceCategory["type"],
             more: Partial<FinanceCategory> = {}): FinanceCategory => ({
  id, name, type, type_label: type, cpa_code: "", position: 0, archived: false,
  system: false, used: false, parent: null, merged_into: null, ...more });

// Between them the rows show every action: Combine, Split, Archive, Restore
// and Remove, with and without each.
const CATEGORIES = [
  cat("fees", "Client fees", "income", { system: true, used: true }),
  cat("travel", "Travel", "expense", { used: true }),
  cat("air", "Airfare", "expense", { parent: "travel", used: true }),
  cat("lodging", "Lodging", "expense", { parent: "travel", position: 1 }),
  cat("meals", "Meals", "expense", { position: 1, used: true }),
  cat("vehicle", "Vehicle", "expense", { position: 2 }),
  cat("old", "Entertainment", "expense", { position: 3, archived: true }),
  cat("draw", "Owner draw", "owner", { used: true }),
  cat("tax", "Sales tax collected", "held", { system: true })];

window.fetch = async () => new Response("[]", {
  status: 200, headers: { "Content-Type": "application/json" } });

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
ReactDOM.createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={client}>
    <MemoryRouter>
      <main style={{ width: 1100 }}>
        <FinanceCategories categories={CATEGORIES} bookkeeping busy={false}
          paidInvoicesId="fees" send={() => undefined} />
      </main>
    </MemoryRouter>
  </QueryClientProvider>,
);

const round = (n: number) => Math.round(n * 100) / 100;

function measure() {
  const rows = Array.from(document.querySelectorAll(".row-actions")).map((row) => ({
    name: row.querySelector("input")?.getAttribute("aria-label") ?? "",
    cells: Array.from(row.querySelectorAll(".row-actions-cell")).map((cell) => {
      const box = cell.getBoundingClientRect();
      const button = cell.querySelector("button");
      if (!button) return { x: round(box.left), w: round(box.width), button: null };
      // The label's own width, laid out: wider than the button means it spills.
      const range = document.createRange();
      range.selectNodeContents(button);
      const inside = button.getBoundingClientRect();
      const text = range.getBoundingClientRect();
      return { x: round(box.left), w: round(box.width), button: {
        label: button.textContent ?? "", x: round(inside.left), w: round(inside.width),
        h: round(inside.height), textLeft: round(text.left), textRight: round(text.right),
        right: round(inside.right), scrollWidth: button.scrollWidth,
        clientWidth: button.clientWidth } };
    }),
  }));
  return { rows };
}

const started = Date.now();
const timer = window.setInterval(async () => {
  const ready = document.querySelectorAll(".row-actions").length > 0;
  if (!ready && Date.now() - started < 8000) return;
  window.clearInterval(timer);
  await document.fonts.ready;
  document.getElementById("layout")!.textContent = JSON.stringify(
    ready ? measure() : { error: "the categories did not render" });
}, 50);
