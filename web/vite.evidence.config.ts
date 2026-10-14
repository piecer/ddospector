import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Owned controlled-transport browser QA: no proxy to any backend or default port.
export default defineConfig({
  plugins: [react()],
  cacheDir: ".cache/vite-evidence",
  server: { host: "127.0.0.1", strictPort: true },
});
