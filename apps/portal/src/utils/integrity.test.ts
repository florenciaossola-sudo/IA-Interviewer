import { describe, expect, it } from "vitest";

import type { EventRecord } from "../types";
import { findIntegrityReport, groupIntegrityEvidence } from "./integrity";

function event(event_id: number, integrity?: Record<string, unknown>): EventRecord {
  return {
    event_id,
    event_type: "turn_completed",
    created_at: "2026-11-17T19:58:27Z",
    payload: integrity ? { integrity_state: integrity } : {},
  };
}

describe("findIntegrityReport", () => {
  it("uses the last available report, including a real zero AAI", () => {
    const report = findIntegrityReport([
      event(1, { aai_index: 0, signal_breakdown: [], baseline_available: false }),
      event(2, { aai_index: 33, signal_breakdown: [{ signal_family: "motion", event_count: 888 }] }),
      event(3, {
        aai_index: 0,
        disposition: "reviewer_visible_only",
        baseline_available: true,
        baseline_answer_length: 120,
        signal_breakdown: [
          { signal_family: "focus", event_count: 27, suppressed: false, evidence: ["focus: answer-input"] },
          { signal_family: "motion", event_count: 1246, suppressed: false, evidence: [] },
          { signal_family: "input", event_count: 0, suppressed: true, evidence: [] },
        ],
        confounders: ["input suppressed by accommodation"],
      }),
      event(4),
    ]);

    expect(report?.aai_index).toBe(0);
    expect(report?.baseline_available).toBe(true);
    expect(report?.baseline_answer_length).toBe(120);
    expect(report?.signal_breakdown).toEqual([
      { signal_family: "focus", event_count: 27, suppressed: false, evidence: ["focus: answer-input"] },
      { signal_family: "motion", event_count: 1246, suppressed: false, evidence: [] },
      { signal_family: "input", event_count: 0, suppressed: true, evidence: [] },
    ]);
    expect(report?.confounders).toEqual(["input suppressed by accommodation"]);
  });

  describe("groupIntegrityEvidence", () => {
    it("counts identical evidence while preserving distinct values and their order", () => {
      expect(groupIntegrityEvidence([
        "focus: answer-input", "blur: answer-input", "focus: answer-input",
        "input: 12", "input: 13", "input: 12",
      ])).toEqual([
        { text: "focus: answer-input", count: 2 },
        { text: "blur: answer-input", count: 1 },
        { text: "input: 12", count: 2 },
        { text: "input: 13", count: 1 },
      ]);
      expect(groupIntegrityEvidence([])).toEqual([]);
    });
  });

  it("returns null if no event contains an integrity report", () => {
    expect(findIntegrityReport([event(1), event(2)])).toBeNull();
    expect(findIntegrityReport([])).toBeNull();
  });
});
