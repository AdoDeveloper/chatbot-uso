import { defineConfig } from "vite";

export default defineConfig({
  esbuild: {
    jsxImportSource: "preact",
    jsx: "automatic",
  },
  build: {
    lib: {
      entry: "src/widget.tsx",
      formats: ["iife"],
      name: "ChatbotWidget",
      fileName: () => "widget",
    },
    rollupOptions: {
      external: [],
      output: {
        inlineDynamicImports: true,
        // Force output as widget.js (not widget.iife.js)
        entryFileNames: "widget.js",
      },
    },
    minify: "esbuild",
    cssCodeSplit: false,
  },
});
