import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAnalytics } from "./useAnalytics";

vi.mock("../../legacy/api.js", () => ({
  compareSnapshots: vi.fn(),
  createAnalyticsSnapshot: vi.fn(),
  listAnalyticsEvaluations: vi.fn(),
  listAnalyticsSnapshots: vi.fn(),
  listAnalyticsTrends: vi.fn(),
  runDriftCheck: vi.fn(),
  runSnapshotSync: vi.fn(),
}));

import {
  compareSnapshots,
  createAnalyticsSnapshot,
  listAnalyticsEvaluations,
  listAnalyticsSnapshots,
  listAnalyticsTrends,
  runDriftCheck,
  runSnapshotSync,
} from "../../legacy/api.js";

const mockCompareSnapshots = vi.mocked(compareSnapshots);
const mockCreateAnalyticsSnapshot = vi.mocked(createAnalyticsSnapshot);
const mockListAnalyticsEvaluations = vi.mocked(listAnalyticsEvaluations);
const mockListAnalyticsSnapshots = vi.mocked(listAnalyticsSnapshots);
const mockListAnalyticsTrends = vi.mocked(listAnalyticsTrends);
const mockRunDriftCheck = vi.mocked(runDriftCheck);
const mockRunSnapshotSync = vi.mocked(runSnapshotSync);

const snapshots = [
  {
    snapshot_id: 1,
    label: "baseline",
    policy_version: "v1",
    prompt_version: "p1",
    created_at: "2026-08-25T10:00:00Z",
  },
  {
    snapshot_id: 2,
    label: "candidate",
    policy_version: "v2",
    prompt_version: "p2",
    created_at: "2026-08-25T11:00:00Z",
  },
];

describe("useAnalytics", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockListAnalyticsSnapshots.mockResolvedValue({ ok: true, status: 200, data: snapshots });
    mockListAnalyticsEvaluations.mockResolvedValue({ ok: true, status: 200, data: [] });
    mockListAnalyticsTrends.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        average_candidate_fallback_rate: 0,
        average_fallback_rate_delta: 0,
        max_candidate_fallback_rate: 0,
        points: [],
      },
    });

    mockCreateAnalyticsSnapshot.mockResolvedValue({ ok: true, status: 200, data: { snapshot_id: 3 } });
    mockRunSnapshotSync.mockResolvedValue({ ok: true, status: 200, data: { snapshot_id: 4 } });
    mockCompareSnapshots.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        comparison: {
          average_score_delta: 0.1,
          completed_run_delta: 2,
          reviewer_override_rate_delta: 0.05,
          route_distribution_delta: { complete: 1 },
          fairness_slice_deltas: [],
          recommendations: [],
        },
      },
    });
    mockRunDriftCheck.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        status: "ok",
        evaluation_id: 10,
        comparison: {
          average_score_delta: 0,
          completed_run_delta: 0,
          reviewer_override_rate_delta: 0,
          route_distribution_delta: {},
          fairness_slice_deltas: [],
          recommendations: [],
        },
      },
    });
  });

  it("loads snapshots on mount and selects baseline/candidate ids", async () => {
    const { result } = renderHook(() => useAnalytics());

    await waitFor(() => {
      expect(result.current.analyticsSnapshots).toHaveLength(2);
      expect(result.current.baselineSnapshotId).toBe("2");
      expect(result.current.candidateSnapshotId).toBe("1");
    });
  });

  it("shows snapshot load error when registry request fails", async () => {
    mockListAnalyticsSnapshots.mockResolvedValueOnce({ ok: false, status: 500, data: null });
    const { result } = renderHook(() => useAnalytics());

    await waitFor(() => {
      expect(result.current.analyticsStatusText).toBe("Analytics request failed with status 500.");
    });
  });

  it("prevents compare when no snapshot ids are selected", async () => {
    mockListAnalyticsSnapshots.mockResolvedValueOnce({ ok: true, status: 200, data: [] });
    const { result } = renderHook(() => useAnalytics());

    await waitFor(() => {
      expect(result.current.analyticsSnapshots).toHaveLength(0);
      expect(result.current.analyticsStatusText).toContain("No snapshots found");
    });

    await act(async () => {
      await result.current.onCompareSnapshots();
    });

    expect(result.current.analyticsStatusText).toBe("Select both baseline and candidate snapshots.");
    expect(mockCompareSnapshots).not.toHaveBeenCalled();
  });

  it("runs drift check and stores comparison", async () => {
    const { result } = renderHook(() => useAnalytics());

    await waitFor(() => {
      expect(result.current.baselineSnapshotId).toBe("2");
      expect(result.current.candidateSnapshotId).toBe("1");
    });

    await act(async () => {
      await result.current.onRunDriftCheck();
    });

    await waitFor(() => {
      expect(result.current.analyticsComparison).not.toBeNull();
      expect(result.current.analyticsStatusText).toContain("Drift check ok. Evaluation #10 saved.");
    });
  });

  it("shows error when snapshot creation fails", async () => {
    mockCreateAnalyticsSnapshot.mockResolvedValueOnce({ ok: false, status: 500, data: null });
    const { result } = renderHook(() => useAnalytics());

    await waitFor(() => {
      expect(result.current.analyticsSnapshots).toHaveLength(2);
    });

    await act(async () => {
      await result.current.onCreateSnapshot();
    });

    expect(result.current.analyticsStatusText).toBe("Snapshot creation failed with status 500.");
  });

  it("shows error when snapshot sync job fails", async () => {
    mockRunSnapshotSync.mockResolvedValueOnce({ ok: false, status: 500, data: null });
    const { result } = renderHook(() => useAnalytics());

    await waitFor(() => {
      expect(result.current.analyticsSnapshots).toHaveLength(2);
    });

    await act(async () => {
      await result.current.onRunSnapshotSyncJob();
    });

    expect(result.current.analyticsStatusText).toBe("Sync job failed with status 500.");
  });

  it("shows error when snapshot comparison fails", async () => {
    mockCompareSnapshots.mockResolvedValueOnce({ ok: false, status: 500, data: null });
    const { result } = renderHook(() => useAnalytics());

    await waitFor(() => {
      expect(result.current.baselineSnapshotId).toBe("2");
      expect(result.current.candidateSnapshotId).toBe("1");
    });

    await act(async () => {
      await result.current.onCompareSnapshots();
    });

    expect(result.current.analyticsStatusText).toBe("Comparison failed with status 500.");
  });

  it("shows error when drift check fails", async () => {
    mockRunDriftCheck.mockResolvedValueOnce({ ok: false, status: 500, data: null });
    const { result } = renderHook(() => useAnalytics());

    await waitFor(() => {
      expect(result.current.baselineSnapshotId).toBe("2");
      expect(result.current.candidateSnapshotId).toBe("1");
    });

    await act(async () => {
      await result.current.onRunDriftCheck();
    });

    expect(result.current.analyticsStatusText).toBe("Drift check failed with status 500.");
  });
});
