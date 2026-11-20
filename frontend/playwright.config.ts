import { defineConfig } from "@playwright/test";
import path from "node:path";

const BASE = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8765";
const chrome = process.env.E2E_CHROME ?? "/usr/bin/google-chrome";
const mic = (wav: string) => ({
  executablePath: chrome,
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
         `--use-file-for-fake-audio-capture=${path.resolve("e2e", wav)}`],
});

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: BASE, headless: true, trace: "retain-on-failure" },
  projects: [
    { name: "speech", testMatch: /walkthrough\.spec\.ts/, use: { launchOptions: mic("speech-like.wav") } },
    { name: "no-microphone", testMatch: /denied\.spec\.ts/, use: { launchOptions: { executablePath: chrome } } },
    { name: "silence", testMatch: /silent\.spec\.ts/, use: { launchOptions: mic("silence.wav") } },
  ],
});
