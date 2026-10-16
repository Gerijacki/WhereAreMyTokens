import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { chunkSizeWarningLimit: 900 },
  test: { include: ["src/**/*.test.ts"] }, // e2e/ belongs to Playwright
  server: {
    port: 5173,
    proxy: { "/api": process.env.WAMT_API ?? "http://localhost:8787" },
  },
});
