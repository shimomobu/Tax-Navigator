const { defineConfig, devices } = require('@playwright/test');
const path = require('path');

module.exports = defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  retries: 0,
  reporter: 'line',
  use: {
    baseURL: 'http://localhost:8001',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    locale: 'ja-JP',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: `python3 -m http.server 8001 --directory ${path.resolve(__dirname, 'app/static')}`,
    url: 'http://localhost:8001',
    reuseExistingServer: true,
    timeout: 5000,
  },
});
