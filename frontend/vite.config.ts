import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 127.0.0.1, not localhost: Node resolves localhost to ::1 but uvicorn binds IPv4.
      "/api": "http://127.0.0.1:8000",
    },
  },
});
