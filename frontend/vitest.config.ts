import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  // Next компилирует JSX сам (jsx: preserve в tsconfig); для vitest включаем
  // автоматический runtime React, чтобы тесты могли рендерить компоненты.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
