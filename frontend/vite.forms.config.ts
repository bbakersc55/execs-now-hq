import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

/** The owner's intake form, built on its own (docs/p14_intake_forms.md).
 *  Its root is src/forms and it imports nothing outside it, so nothing of the
 *  app, and no word of it, is in what an owner downloads. Django serves the
 *  result at /static/forms/ (apps/intake/hosts.py). Built after the app's own
 *  bundle, which empties dist/ first. */
export default defineConfig(({ command }) => ({
  root: resolve(__dirname, "src/forms"),
  base: command === "build" ? "/static/forms/" : "/",
  plugins: [react()],
  publicDir: false,
  server: { port: 5201, strictPort: true,
            proxy: { "/api": { target: "http://localhost:8100", changeOrigin: false } } },
  build: {
    outDir: resolve(__dirname, "dist/forms"),
    emptyOutDir: true,
    assetsInlineLimit: 0,
  },
}));
