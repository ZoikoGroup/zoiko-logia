import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
  resolve: {
    // Mirrors the "@/*" path alias in tsconfig.json, so tests import modules
    // by the same specifier the app does.
    alias: { "@": path.resolve(__dirname, ".") },
  },
});
