import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Ports 5200 / 8100 are fixed by CLAUDE.md and deliberately unusual.
export default defineConfig({
  plugins: [react()],
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
});
