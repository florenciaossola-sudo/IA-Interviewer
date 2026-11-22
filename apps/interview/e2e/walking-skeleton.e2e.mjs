import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import process from "node:process";
import { setTimeout as sleep } from "node:timers/promises";

import { chromium } from "playwright";

const PROJECT_ROOT = process.cwd();
const API_URL = "http://127.0.0.1:8081/health";
const UI_URL = "http://127.0.0.1:4174";

function stopProcess(child) {
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/t", "/f"]);
  } else {
    child.kill();
  }
}

function startProcess(command, args, label) {
  const child = spawn(command, args, {
    cwd: PROJECT_ROOT,
    stdio: ["ignore", "pipe", "pipe"],
    shell: process.platform === "win32",
  });

  child.stdout.on("data", (chunk) => {
    process.stdout.write(`[${label}] ${chunk}`);
  });

  child.stderr.on("data", (chunk) => {
    process.stderr.write(`[${label}] ${chunk}`);
  });

  return child;
}

async function waitForHttp(url, timeoutMs = 20_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // Keep polling until timeout.
    }
    await sleep(300);
  }

  throw new Error(`Timed out waiting for ${url}`);
}

async function runE2E() {
  let apiProc;
  let uiProc;

  let apiAlreadyRunning = false;
  try {
    const response = await fetch(API_URL);
    apiAlreadyRunning = response.ok;
  } catch {
    apiAlreadyRunning = false;
  }

  let uiAlreadyRunning = false;
  try {
    const response = await fetch("http://127.0.0.1:4174");
    uiAlreadyRunning = response.ok;
  } catch {
    uiAlreadyRunning = false;
  }

  if (!apiAlreadyRunning) {
    apiProc = startProcess(
      "py",
      ["-3", "-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", "8081"],
      "api"
    );
  }

  if (!uiAlreadyRunning) {
    const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
    uiProc = startProcess(
      npmCommand,
      ["run", "--workspace", "@ai-interviewer/interview", "dev"],
      "ui"
    );
  }

  try {
    await waitForHttp(API_URL);
    await waitForHttp("http://127.0.0.1:4174");

    let browser;
    try {
      browser = await chromium.launch({ channel: "msedge" });
    } catch {
      browser = await chromium.launch();
    }
    const page = await browser.newPage();

    await page.goto(UI_URL, { waitUntil: "domcontentloaded" });
    await page.getByRole("checkbox", { name: "I understand the disclosure and want to continue." }).check();
    await page.getByRole("checkbox", { name: "Enable focus telemetry for this session." }).check();
    await page.locator("#accommodation-motion").check();
    await page.locator("#accommodation-content").check();
    await page.getByRole("button", { name: "Accept disclosure" }).click();
    await page.getByText("Disclosure accepted. You can start the interview now.").waitFor();
    await page.getByRole("button", { name: "Start Interview" }).click();
    await page.getByText("Warm-up calibration").waitFor();

    await page.locator("#answer-input").fill("I recently improved a service reliability problem.");
    await page.getByRole("button", { name: "Submit Answer" }).click();
    await page.getByText("Question 1 of 5").waitFor();
    await page.locator("#answer-input").fill("## Baseline-aware answer\n\nI debug production incidents by tracing failures through logs.\n\n```js\nconst healthy = true;\n```");
    await page.getByRole("button", { name: "Preview" }).click();
    await page.locator("#answer-preview").getByText("Baseline-aware answer").waitFor();
    await page.getByRole("button", { name: "Code mode" }).click();
    await page.getByRole("button", { name: "Edit" }).click();

    const answers = [
      "I debug production incidents and find root cause quickly.",
      "I preserve backward compatibility using API versioning and deprecation plans.",
      "I improve CI reliability by removing flaky tests and enforcing deterministic checks.",
      "I investigate regressions with small reproducible test cases.",
      "I communicate tradeoffs and monitor the rollout after release."
    ];

    for (let i = 0; i < answers.length; i += 1) {
      await page.locator("#answer-input").fill(answers[i]);
      await page.getByRole("button", { name: "Submit Answer" }).click();

      if (i < answers.length - 1) {
        await page.getByText(`Question ${i + 2} of 5`).waitFor();
      }
    }

    await page.locator("#completion-message").getByText("Muchas gracias por su participación.").waitFor();
    const status = await page.locator("#status-text").innerText();
    assert.match(status, /Muchas gracias/i);

    await browser.close();
    console.log("Phase 1 E2E passed.");
  } finally {
    if (apiProc) {
      stopProcess(apiProc);
    }
    if (uiProc) {
      stopProcess(uiProc);
    }
  }
}

runE2E().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
