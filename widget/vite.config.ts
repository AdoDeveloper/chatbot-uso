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
        // Fuerza la salida como widget.js (no widget.iife.js)
        entryFileNames: "widget.js",
      },
    },
    minify: "esbuild",
    cssCodeSplit: false,
  },
});
