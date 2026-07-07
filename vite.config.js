import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";

export default defineConfig({
  plugins: [react()],
  cacheDir: "node_modules/.vite-worktual",
  optimizeDeps: {
    include: [
      "@monaco-editor/react",
      "lucide-react",
      "react",
      "react-dom",
      "react-dom/client",
      "react/jsx-dev-runtime",
      "react/jsx-runtime",
    ],
  },
  server: {
    host: true,
    port: 5174,
    strictPort: true,
    https: {
      cert: fs.readFileSync("certs/worktual-lan.pem"),
      key: fs.readFileSync("certs/worktual-lan-key.pem"),
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
      },
    },
  },
});
