export default {
  testDir: ".",
  use: {
    baseURL: "http://127.0.0.1:3000",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : undefined,
  },
  webServer: {
    command: "pnpm run serve",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: false,
    timeout: 30000,
  },
};
