import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./browser",
  workers: 1,
  fullyParallel: false,
  use: {
    headless: true,
    channel: "chrome",
    viewport: { width: 1440, height: 1100 },
  },
});
