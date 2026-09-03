import { defineConfig, devices } from "@playwright/test";

/*
 * Сквозные сценарии против локально поднятых бэкенда (SQLite, fake-провайдер
 * моделей) и фронтенда. Камера и микрофон — фейковые устройства Chromium:
 * никаких разрешений спрашивать не нужно, а запись даёт настоящий WebM.
 */
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000/api";

export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    video: process.env.E2E_VIDEO ? "on" : "retain-on-failure",
    launchOptions: {
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
      ],
    },
    permissions: ["camera", "microphone"],
    locale: "ru-RU",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        // Локально без скачанного Chromium можно взять установленный Chrome/Edge:
        // E2E_CHANNEL=chrome | msedge.
        ...(process.env.E2E_CHANNEL ? { channel: process.env.E2E_CHANNEL } : {}),
      },
    },
  ],
  metadata: { apiUrl: API_URL },
});
