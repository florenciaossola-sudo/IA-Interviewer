import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  root: "reviewer",
  cacheDir: "../node_modules/.vite-reviewer",
  plugins: [react()],
  build: {
    outDir: "../dist/reviewer",
    emptyOutDir: true,
  },
});
