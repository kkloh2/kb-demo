import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Node global (the project has no @types/node).
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 127.0.0.1, not localhost: Node resolves localhost to ::1 but uvicorn binds IPv4.
      // DATAHUB_API_TARGET points a second dev server at another backend (e.g. a test one).
      "/api": process.env.DATAHUB_API_TARGET ?? "http://127.0.0.1:8000",
    },
  },
});
