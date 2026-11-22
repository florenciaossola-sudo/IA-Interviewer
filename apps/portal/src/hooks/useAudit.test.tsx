import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAudit } from "./useAudit";

vi.mock("../../legacy/api.js", () => ({
  getReviewQueue: vi.fn(),
  getRunAudit: vi.fn(),
  submitRunReview: vi.fn(),
}));

import { getReviewQueue, getRunAudit, submitRunReview } from "../../legacy/api.js";

const mockGetReviewQueue = vi.mocked(getReviewQueue);
const mockGetRunAudit = vi.mocked(getRunAudit);
const mockSubmitRunReview = vi.mocked(submitRunReview);

const queueItem = {
  run_id: "iv_queue_1",
  role: "backend_engineer",
  doc_type: "role_description",
  updated_at: "2026-08-25T10:00:00Z",
};

const auditBundle = {
  run: {
    run_id: "iv_run_1",
    status: "completed",
    role: "backend_engineer",
    doc_type: "role_description",
    created_at: "2026-08-25T10:00:00Z",
    updated_at: "2026-08-25T10:02:00Z",
  },
  events: [],
  checkpoints: [],
};

describe("useAudit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetReviewQueue.mockResolvedValue({ ok: true, status: 200, data: [queueItem] });
    mockGetRunAudit.mockResolvedValue({ ok: true, status: 200, data: auditBundle });
    mockSubmitRunReview.mockResolvedValue({
      ok: true,
      status: 200,
      data: { review: { decision: "approved" } },
    });
    window.history.replaceState({}, "", "/");
  });

  it("loads queue on mount", async () => {
    const { result } = renderHook(() => useAudit());

    await waitFor(() => {
      expect(result.current.queueItems).toHaveLength(1);
    });

    expect(result.current.queueItems[0]?.run_id).toBe("iv_queue_1");
    expect(mockGetReviewQueue).toHaveBeenCalled();
  });

  it("shows queue error when queue request fails", async () => {
    mockGetReviewQueue.mockResolvedValueOnce({ ok: false, status: 500, data: null });
    const { result } = renderHook(() => useAudit());

    await waitFor(() => {
      expect(result.current.queueError).toBe("Could not load the review queue.");
      expect(result.current.queueItems).toHaveLength(0);
    });
  });

  it("loads audit and updates status", async () => {
    const { result } = renderHook(() => useAudit());

    await act(async () => {
      await result.current.loadAudit("iv_run_1");
    });

    await waitFor(() => {
      expect(result.current.auditBundle?.run.run_id).toBe("iv_run_1");
      expect(result.current.statusText).toContain("Loaded audit bundle for iv_run_1");
    });
  });

  it("clears review fields when loading a different run", async () => {
    mockGetRunAudit
      .mockResolvedValueOnce({ ok: true, status: 200, data: auditBundle })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: { ...auditBundle, run: { ...auditBundle.run, run_id: "iv_run_2" } },
      });
    const { result } = renderHook(() => useAudit());

    await act(async () => {
      await result.current.loadAudit("iv_run_1");
    });
    act(() => {
      result.current.setDecision("overridden");
      result.current.setRationale("Previous run rationale");
    });

    await act(async () => {
      await result.current.loadAudit("iv_run_2");
    });

    expect(result.current.decision).toBe("approved");
    expect(result.current.rationale).toBe("");
    expect(result.current.reviewStatusText).toBe("");
    expect(result.current.auditBundle?.run.run_id).toBe("iv_run_2");
  });

  it("requires rationale before submitting review", async () => {
    const { result } = renderHook(() => useAudit());

    await act(async () => {
      await result.current.loadAudit("iv_run_1");
    });

    await act(async () => {
      await result.current.onSubmitReview();
    });

    expect(result.current.reviewStatusText).toBe("Rationale is required.");
    expect(mockSubmitRunReview).not.toHaveBeenCalled();
  });

  it("shows 404 message when audit bundle does not exist", async () => {
    mockGetRunAudit.mockResolvedValueOnce({ ok: false, status: 404, data: null });
    const { result } = renderHook(() => useAudit());

    await act(async () => {
      await result.current.loadAudit("iv_missing");
    });

    expect(result.current.statusText).toBe("No audit bundle found for that run ID.");
    expect(result.current.auditBundle).toBeNull();
  });

  it("shows generic error for non-404 audit failures", async () => {
    mockGetRunAudit.mockResolvedValueOnce({ ok: false, status: 500, data: null });
    const { result } = renderHook(() => useAudit());

    await act(async () => {
      await result.current.loadAudit("iv_error");
    });

    expect(result.current.statusText).toBe("Request failed with status 500.");
    expect(result.current.auditBundle).toBeNull();
  });

  it("shows validation message for 400 review submission", async () => {
    mockSubmitRunReview.mockResolvedValueOnce({ ok: false, status: 400, data: null });
    const { result } = renderHook(() => useAudit());

    await act(async () => {
      await result.current.loadAudit("iv_run_1");
    });

    act(() => {
      result.current.setRationale("Because reviewer said so");
    });

    await act(async () => {
      await result.current.onSubmitReview();
    });

    expect(result.current.reviewStatusText).toBe("Review requires a valid decision and rationale.");
  });

  it("shows generic error for non-400 review failures", async () => {
    mockSubmitRunReview.mockResolvedValueOnce({ ok: false, status: 500, data: null });
    const { result } = renderHook(() => useAudit());

    await act(async () => {
      await result.current.loadAudit("iv_run_1");
    });

    act(() => {
      result.current.setRationale("Manual review rationale");
    });

    await act(async () => {
      await result.current.onSubmitReview();
    });

    expect(result.current.reviewStatusText).toBe("Request failed with status 500.");
  });
});
