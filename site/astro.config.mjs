// The Execs NOW HQ marketing site (2026-11-09). Static output; server.mjs
// serves dist/ on Railway and forwards the demo form to the app.
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: "https://www.execsnowhq.com",
  output: "static",
  trailingSlash: "never",
  build: { format: "directory", inlineStylesheets: "always" },
  compressHTML: true,
  vite: { plugins: [tailwindcss()] },
});
