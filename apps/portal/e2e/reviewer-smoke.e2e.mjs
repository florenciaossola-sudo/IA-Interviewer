import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import process from "node:process";
import { setTimeout as sleep } from "node:timers/promises";

import { chromium } from "playwright";

const PROJECT_ROOT = process.cwd();
const API_ORIGIN = process.env.E2E_API_ORIGIN ?? "http://127.0.0.1:8081";
const API_HEALTH_URL = `${API_ORIGIN}/health`;
const PORTAL_URL = "http://127.0.0.1:4175";

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

async function waitForHttp(url, timeoutMs = 30_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // Keep polling.
    }
    await sleep(300);
  }

  throw new Error(`Timed out waiting for ${url}`);
}

async function createCompletedRun() {
  const startResponse = await fetch(`${API_ORIGIN}/run/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      role: "backend_engineer",
      doc_type: "role_description",
    }),
  });
  assert.equal(startResponse.ok, true);

  const startPayload = await startResponse.json();
  const runId = startPayload.run_id;

  const warmupResponse = await fetch(`${API_ORIGIN}/run/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, answer: "I recently improved a service reliability problem." }),
  });
  assert.equal(warmupResponse.ok, true);

  const answers = [
    "I debug production incidents by building a timeline and isolating the failing component.",
    "I keep APIs backward compatible using explicit versioning and deprecation policies.",
    "I improve CI reliability by deflaking tests and adding deterministic checks.",
    "I investigate regressions with small reproducible test cases.",
    "I communicate tradeoffs and monitor the rollout after release.",
  ];

  let completed = false;
  for (const answer of answers) {
    const response = await fetch(`${API_ORIGIN}/run/answer`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        run_id: runId,
        answer,
      }),
    });

    assert.equal(response.ok, true);
    const payload = await response.json();
    if (payload.completed) {
      completed = true;
      break;
    }
  }

  assert.equal(completed, true, "Interview did not finish within the available answers");
  return runId;
}

async function runE2E() {
  let apiProc;
  let portalProc;
  let browser;

  let apiAlreadyRunning = false;
  try {
    const response = await fetch(API_HEALTH_URL);
    apiAlreadyRunning = response.ok;
  } catch {
    apiAlreadyRunning = false;
  }

  let portalAlreadyRunning = false;
  try {
    const response = await fetch(PORTAL_URL);
    portalAlreadyRunning = response.ok;
  } catch {
    portalAlreadyRunning = false;
  }

  if (!apiAlreadyRunning) {
    if (API_ORIGIN !== "http://127.0.0.1:8081") {
      throw new Error(`Start the test API at ${API_ORIGIN} before running E2E`);
    }
    apiProc = startProcess(
      "py",
      ["-3", "-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", "8081"],
      "api"
    );
  }

  if (!portalAlreadyRunning) {
    const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
    portalProc = startProcess(
      npmCommand,
      ["run", "--workspace", "@ai-interviewer/portal", "dev:reviewer"],
      "portal"
    );
  }

  try {
    await waitForHttp(API_HEALTH_URL);
    await waitForHttp(PORTAL_URL);

    const runId = await createCompletedRun();

    try {
      browser = await chromium.launch({ channel: "msedge" });
    } catch {
      browser = await chromium.launch();
    }

    const page = await browser.newPage();
    if (API_ORIGIN !== "http://127.0.0.1:8081") {
      await page.route("http://127.0.0.1:8081/**", async (route) => {
        const url = new URL(route.request().url());
        const response = await route.fetch({ url: `${API_ORIGIN}${url.pathname}${url.search}` });
        await route.fulfill({ response });
      });
    }
    await page.goto(PORTAL_URL, { waitUntil: "domcontentloaded" });
    await page.locator("#run-id-input").waitFor();

    await page.locator("#run-id-input").fill(runId);
    await page.getByRole("button", { name: "Load audit" }).click();
    await page.getByText(`Loaded audit bundle for ${runId}.`).waitFor();
    await page.getByRole("heading", { name: "Event Stream" }).waitFor();

    await page.locator("#rationale-input").fill("Manual reviewer confirmation from e2e smoke.");
    const reviewResponse = page.waitForResponse(
      (response) => response.url().includes(`/runs/${runId}/review`) && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Submit review" }).click();
    assert.equal((await reviewResponse).ok(), true);
    const auditResponse = await fetch(`${API_ORIGIN}/runs/${runId}/audit`);
    const auditPayload = await auditResponse.json();
    assert.equal(auditPayload.run.status, "finalized");

    console.log("Portal reviewer E2E passed.");
  } finally {
    if (browser) {
      await browser.close();
    }
    if (apiProc) {
      stopProcess(apiProc);
    }
    if (portalProc) {
      stopProcess(portalProc);
    }
  }
}

runE2E().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
