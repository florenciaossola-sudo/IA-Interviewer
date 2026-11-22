import { resolve } from "node:path";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        admin: resolve(__dirname, "index.html"),
        reviewer: resolve(__dirname, "reviewer.html"),
      },
    },
  },
});
