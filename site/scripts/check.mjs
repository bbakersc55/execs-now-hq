// The site's own checks, run on a finished build (`npm run build && npm run check`):
// every internal link and asset in every page resolves to a file in dist/,
// every page has a title, a meta description, a canonical URL and Open Graph
// tags, the GA script appears only when PUBLIC_GA4_ID was set at build, and
// no page says "tenant". Exits 1 on any failure.
import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const dist = resolve(import.meta.dirname, "../dist");
const pages = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path);
    else if (name.endsWith(".html")) pages.push(path);
  }
})(dist);

const failures = [];
const fail = (page, why) => failures.push(`${page.replace(dist, "")}: ${why}`);
const exists = (url) => {
  const path = decodeURIComponent(url.split("#")[0].split("?")[0]);
  if (path === "" || path === "/") return existsSync(join(dist, "index.html"));
  const base = join(dist, path);
  return [base, join(base, "index.html"), base + ".html"].some((p) => existsSync(p) && statSync(p).isFile());
};
const gaExpected = Boolean((process.env.PUBLIC_GA4_ID || "").trim());

for (const page of pages) {
  const html = readFileSync(page, "utf8");
  if (!/<title>[^<]+<\/title>/.test(html)) fail(page, "no <title>");
  if (!/<meta name="description" content="[^"]{40,}"/.test(html)) fail(page, "no meta description");
  if (!/<link rel="canonical" href="https:\/\/www\.execsnowhq\.com/.test(html)) fail(page, "no canonical");
  for (const tag of ["og:title", "og:description", "og:image", "og:url"]) {
    if (!html.includes(`property="${tag}"`)) fail(page, `no ${tag}`);
  }
  if (html.includes("googletagmanager") !== gaExpected) fail(page, `GA script ${gaExpected ? "missing" : "present without PUBLIC_GA4_ID"}`);
  const text = html.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>|<[^>]+>/g, " ");
  if (/\btenants?\b/i.test(text)) fail(page, 'says "tenant"');
  const refs = [...html.matchAll(/(?:href|src|poster)="([^"]+)"/g), ...html.matchAll(/srcset="([^"]+)"/g)]
    .flatMap((m) => m[0].startsWith("srcset") ? m[1].split(",").map((s) => s.trim().split(/\s+/)[0]) : [m[1]]);
  for (const ref of refs) {
    if (!ref.startsWith("/") || ref.startsWith("//")) continue;
    if (ref.startsWith("/api/")) continue;
    if (!exists(ref)) fail(page, `broken link or asset ${ref}`);
  }
  for (const m of html.matchAll(/href="#([^"]+)"/g)) {
    if (!html.includes(`id="${m[1]}"`)) fail(page, `anchor #${m[1]} has no target`);
  }
}
for (const m of readFileSync(join(dist, "index.html"), "utf8").matchAll(/href="\/#([^"]+)"/g)) {
  if (!readFileSync(join(dist, "index.html"), "utf8").includes(`id="${m[1]}"`)) failures.push(`/#${m[1]} has no target on the home page`);
}
for (const file of ["sitemap.xml", "robots.txt", "404.html", "og.png", "favicon.ico"]) {
  if (!existsSync(join(dist, file))) failures.push(`dist/${file} missing`);
}

if (failures.length) {
  console.error(`check: ${failures.length} problem(s)\n  ` + failures.join("\n  "));
  process.exit(1);
}
console.log(`check: ${pages.length} pages, all links and assets resolve, meta complete, GA ${gaExpected ? "on" : "off"}.`);
