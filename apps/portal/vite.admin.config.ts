import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  root: "admin",
  cacheDir: "../node_modules/.vite-admin",
  plugins: [react()],
  build: {
    outDir: "../dist/admin",
    emptyOutDir: true,
  },
});
