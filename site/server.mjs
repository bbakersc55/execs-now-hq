// The marketing site's server on Railway (service enhq-site). No
// dependencies: Node's own http, fs and zlib.
//
// - Serves the static build in dist/: /pricing -> dist/pricing/index.html,
//   anything missing -> dist/404.html with a 404, gzip or brotli for text,
//   long caching for fingerprinted files.
// - Sends the bare domain to www (the canonical host).
// - POST /api/lead: the demo form. Forwarded server to server to the app's
//   POST /api/public/leads with the shared secret (SITE_LEAD_TOKEN), which
//   never reaches the browser, and the visitor's IP for the app's rate limit.
//   A form post without JavaScript is answered with a redirect to
//   /demo/thanks or /demo/error; a fetch gets the app's status and JSON.
// - GET /healthz for Railway's health check.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";
import { SITE_URL } from "./src/site-url.mjs";
import { brotliCompressSync, gzipSync, constants as Z } from "node:zlib";

const PORT = Number(process.env.PORT || 4321);
const ROOT = resolve(import.meta.dirname, "dist");
const LEAD_URL = process.env.LEAD_FORWARD_URL || "https://app.getexecutivesnow.com/api/public/leads";
const LEAD_TOKEN = process.env.SITE_LEAD_TOKEN || "";
const CANONICAL = new URL(SITE_URL).host;
const BARE = CANONICAL.replace(/^www\./, "");
const MAX_BODY = 16 * 1024;

const TYPES = {
  ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
  ".xml": "application/xml; charset=utf-8", ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
  ".ico": "image/x-icon", ".woff2": "font/woff2", ".mp4": "video/mp4", ".webmanifest": "application/manifest+json",
};
const COMPRESSIBLE = new Set([".html", ".css", ".js", ".json", ".xml", ".txt", ".svg", ".webmanifest"]);
const SECURITY = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "X-Frame-Options": "DENY",
  "Strict-Transport-Security": "max-age=31536000",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
};

const cache = new Map(); // path -> { body, gzip, br }

async function load(file) {
  if (cache.has(file)) return cache.get(file);
  const body = await readFile(file);
  const entry = { body };
  if (COMPRESSIBLE.has(extname(file)) && body.length > 512) {
    entry.gzip = gzipSync(body, { level: 9 });
    entry.br = brotliCompressSync(body, { params: { [Z.BROTLI_PARAM_QUALITY]: 11 } });
  }
  cache.set(file, entry);
  return entry;
}

async function isFile(path) {
  try { return (await stat(path)).isFile(); } catch { return false; }
}

async function resolveFile(urlPath) {
  // A malformed escape ("/%c0") names no file: a 404, not a 500 and a stack.
  let decoded;
  try { decoded = decodeURIComponent(urlPath); } catch { return null; }
  const clean = normalize(decoded).replace(/^(\.\.[/\\])+/, "");
  const base = join(ROOT, clean);
  if (!base.startsWith(ROOT)) return null;
  for (const candidate of [base, join(base, "index.html"), base + ".html"]) {
    if (await isFile(candidate)) return candidate;
  }
  return null;
}

function cacheControl(urlPath, ext) {
  if (urlPath.startsWith("/_astro/") || urlPath.startsWith("/fonts/")) return "public, max-age=31536000, immutable";
  if (ext === ".html" || ext === ".xml" || ext === ".txt") return "public, max-age=0, must-revalidate";
  return "public, max-age=604800";
}

async function sendFile(req, res, file, status, urlPath) {
  const ext = extname(file);
  const entry = await load(file);
  const headers = { ...SECURITY, "Content-Type": TYPES[ext] || "application/octet-stream",
    "Cache-Control": cacheControl(urlPath, ext), Vary: "Accept-Encoding" };
  const accept = String(req.headers["accept-encoding"] || "");
  let body = entry.body;
  if (entry.br && /\bbr\b/.test(accept)) { body = entry.br; headers["Content-Encoding"] = "br"; }
  else if (entry.gzip && /\bgzip\b/.test(accept)) { body = entry.gzip; headers["Content-Encoding"] = "gzip"; }
  headers["Content-Length"] = body.length;
  res.writeHead(status, headers);
  res.end(req.method === "HEAD" ? undefined : body);
}

function readBody(req) {
  return new Promise((ok, fail) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > MAX_BODY) { fail(new Error("too large")); req.destroy(); return; }
      chunks.push(c);
    });
    req.on("end", () => ok(Buffer.concat(chunks).toString("utf8")));
    req.on("error", fail);
  });
}

const FIELDS = ["name", "email", "practice_name", "discipline", "email_platform", "wants", "message", "website"];

async function lead(req, res) {
  const wantsJson = String(req.headers.accept || "").includes("application/json");
  const reply = (status, ok, detail) => {
    if (wantsJson) {
      res.writeHead(status, { ...SECURITY, "Content-Type": "application/json", "Cache-Control": "no-store" });
      res.end(JSON.stringify(detail ? { ok, detail } : { ok }));
    } else {
      res.writeHead(303, { ...SECURITY, Location: ok ? "/demo/thanks" : "/demo/error", "Cache-Control": "no-store" });
      res.end();
    }
  };
  let raw;
  try { raw = await readBody(req); } catch { return reply(413, false); }
  let data = {};
  try {
    data = String(req.headers["content-type"] || "").includes("application/json")
      ? JSON.parse(raw) : Object.fromEntries(new URLSearchParams(raw));
  } catch { return reply(400, false); }
  const payload = {};
  for (const key of FIELDS) if (typeof data[key] === "string") payload[key] = data[key].slice(0, 2000);
  if (!LEAD_TOKEN) {
    console.error("lead: SITE_LEAD_TOKEN is not set; the form cannot reach the app.");
    return reply(503, false);
  }
  const visitor = String(req.headers["x-forwarded-for"] || req.socket.remoteAddress || "").split(",")[0].trim();
  try {
    const response = await fetch(LEAD_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json",
        "X-Site-Lead-Token": LEAD_TOKEN, "X-Lead-Client-IP": visitor },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10_000),
    });
    if (response.ok) return reply(200, true);
    console.error(`lead: the app answered ${response.status}.`);
    if (response.status === 429) return reply(429, false);
    if (response.status === 400) {
      // The app's plain message for the field that's wrong ("Please enter a
      // valid email address."), shown under the form.
      const body = await response.json().catch(() => ({}));
      return reply(400, false, typeof body.detail === "string" ? body.detail.slice(0, 200) : undefined);
    }
    return reply(502, false);
  } catch (error) {
    console.error(`lead: could not reach the app: ${error.message}`);
    return reply(502, false);
  }
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", "http://localhost");
    const host = String(req.headers.host || "").toLowerCase();
    if (host === BARE && BARE !== CANONICAL) {
      res.writeHead(301, { Location: `https://${CANONICAL}${url.pathname}${url.search}` });
      return res.end();
    }
    if (url.pathname === "/healthz") { res.writeHead(200, { "Content-Type": "text/plain" }); return res.end("ok"); }
    if (url.pathname === "/api/lead") {
      if (req.method !== "POST") { res.writeHead(405, { Allow: "POST" }); return res.end(); }
      return await lead(req, res);
    }
    if (req.method !== "GET" && req.method !== "HEAD") { res.writeHead(405, { Allow: "GET, HEAD" }); return res.end(); }
    if (url.pathname.length > 1 && url.pathname.endsWith("/")) {
      res.writeHead(301, { Location: url.pathname.replace(/\/+$/, "") + url.search });
      return res.end();
    }
    const file = await resolveFile(url.pathname);
    if (file) return await sendFile(req, res, file, 200, url.pathname);
    return await sendFile(req, res, join(ROOT, "404.html"), 404, "/404");
  } catch (error) {
    console.error(error);
    if (!res.headersSent) res.writeHead(500, { "Content-Type": "text/plain" });
    res.end("Server error");
  }
});

server.listen(PORT, () => console.log(`enhq-site listening on ${PORT}`));
