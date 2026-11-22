import assert from "node:assert/strict";
import test from "node:test";

import type { InterviewRun } from "./index.js";

test("shared-types supports valid interview run status values", () => {
  const run: InterviewRun = {
    runId: "iv_123abc",
    status: "in_progress"
  };

  assert.equal(run.status, "in_progress");
});
