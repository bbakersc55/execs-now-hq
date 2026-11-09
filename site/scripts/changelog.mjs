// Builds src/data/changelog.json from the release record in
// docs/phase7_cutover_runbook.md: every "### Release N, <date>" heading and
// every "**Observed at Release N (<date> …" paragraph gives a release and
// its date. The public line for each comes from src/data/changelog-lines.json.
//
// Runs before every build (`npm run build`). On Railway the service's root is
// site/, so docs/ isn't there: the script then keeps the committed JSON.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const runbook = resolve(here, "../../docs/phase7_cutover_runbook.md");
const out = resolve(here, "../src/data/changelog.json");
const lines = JSON.parse(readFileSync(resolve(here, "../src/data/changelog-lines.json"), "utf8"));

if (!existsSync(runbook)) {
  console.log("changelog: no docs/ here (a build from site/ alone); keeping the committed changelog.json.");
  process.exit(0);
}

const text = readFileSync(runbook, "utf8");
const releases = new Map();
for (const m of text.matchAll(/^### Release (\d+), (\d{4}-\d{2}-\d{2})/gm)) releases.set(Number(m[1]), m[2]);
for (const m of text.matchAll(/\*\*Observed at Release (\d+) \((\d{4}-\d{2}-\d{2})/g)) releases.set(Number(m[1]), m[2]);

const missing = [];
const entries = [...releases.entries()]
  .sort((a, b) => b[0] - a[0])
  .map(([n, date]) => {
    const line = lines[String(n)];
    if (!line) missing.push(n);
    return { release: n, date, line: line ?? "" };
  });

writeFileSync(out, JSON.stringify(entries, null, 2) + "\n");
console.log(`changelog: ${entries.length} releases from the runbook, newest ${entries[0]?.release}.`);
if (missing.length) {
  console.warn(`changelog: WARNING, no public line yet for release(s) ${missing.join(", ")}; add them to src/data/changelog-lines.json.`);
}
