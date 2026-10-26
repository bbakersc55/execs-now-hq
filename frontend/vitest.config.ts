import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // A test's own limit (2026-10-26). Heavy screens that take about a second
    // alone ran past the default five under the whole suite's load, a
    // different one each run. A real failure fails its assertion, not the clock.
    testTimeout: 15000,
  },
});
