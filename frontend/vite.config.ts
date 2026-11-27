import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";

/**
 * Subresource Integrity on the built page's scripts (P16,
 * docs/p16_card_page_scripts.md): each `<script src="/static/…">` in
 * dist/index.html gets the SHA-384 of the file as written, so a browser runs
 * it only if it is exactly what this build made. Done after the files are
 * written, from the files themselves. Browsers have no integrity check for
 * the parts the bundle loads later; the policy (ENHQ's own address only) and
 * the daily check's content hashes cover those.
 */
function subresourceIntegrity(): Plugin {
  let outDir = "dist";
  return {
    name: "enhq-subresource-integrity",
    apply: "build",
    configResolved(config) { outDir = resolve(config.root, config.build.outDir); },
    closeBundle() {
      const index = resolve(outDir, "index.html");
      if (!existsSync(index)) return;
      const html = readFileSync(index, "utf8").replace(
        /<script\b([^>]*?)\bsrc="\/static\/([^"]+\.js)"([^>]*)><\/script>/g,
        (tag, before: string, file: string, after: string) => {
          if (/\bintegrity=/.test(tag)) return tag;
          const hash = createHash("sha384").update(readFileSync(resolve(outDir, file)))
            .digest("base64");
          return `<script${before}integrity="sha384-${hash}" src="/static/${file}"${after}></script>`;
        });
      writeFileSync(index, html);
    },
  };
}

// Ports 5200 / 8100 are fixed by CLAUDE.md and deliberately unusual.
export default defineConfig(({ command }) => ({
  // Built for Django to serve (Phase 7): WhiteNoise serves the bundle under
  // /static/, so the built index.html must ask for its assets there. The dev
  // server keeps "/".
  base: command === "build" ? "/static/" : "/",
  plugins: [react(), subresourceIntegrity()],
  server: {
    port: 5200,
    strictPort: true,
    proxy: {
      "/api": { target: "http://localhost:8100", changeOrigin: false },
      "/auth": { target: "http://localhost:8100", changeOrigin: false },
      "/accounts": { target: "http://localhost:8100", changeOrigin: false },
      "/admin": { target: "http://localhost:8100", changeOrigin: false },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
}));
