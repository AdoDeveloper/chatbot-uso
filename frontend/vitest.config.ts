import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Mirrors the "@/*" path mapping in tsconfig.json so component imports
      // like `@/lib/api` resolve under Vitest the same way they do under Next.js.
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Disable PostCSS auto-discovery — the Tailwind v4 postcss.config.mjs uses
  // the new "@tailwindcss/postcss" plugin which Vite's PostCSS pipeline can't
  // load. Tests don't need CSS anyway.
  css: { postcss: { plugins: [] } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    // Match co-located *.test.tsx and tests/ directory
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    // Exclude Next.js build output and Playwright e2e folder.
    exclude: ["node_modules", ".next", "e2e", "tests-e2e"],
  },
});
