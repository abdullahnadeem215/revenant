import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev server runs on port 5173. The API's CORS list allows http://localhost:5173 and
// http://127.0.0.1:5173, so the port must stay fixed.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "localhost",
    port: 5173,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
