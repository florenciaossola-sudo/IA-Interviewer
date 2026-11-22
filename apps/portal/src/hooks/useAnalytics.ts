import { useEffect, useState } from "react";

import {
  compareSnapshots,
  createAnalyticsSnapshot,
  listAnalyticsEvaluations,
  listAnalyticsSnapshots,
  listAnalyticsTrends,
  runDriftCheck,
  runSnapshotSync,
} from "../../legacy/api.js";
import type { ComparisonPayload, EvaluationItem, SnapshotItem, TrendPayload } from "../types";
import { asRecord } from "../utils/integrity";

const DEFAULT_POLICY_VERSION = "adaptive-policy.v1";
const DEFAULT_PROMPT_VERSION = "interviewer-prompt.v1";

export function useAnalytics() {
  const [analyticsStatusText, setAnalyticsStatusText] = useState("Load or generate analytics snapshots.");
  const [analyticsLabelInput, setAnalyticsLabelInput] = useState("");
  const [analyticsPolicyInput, setAnalyticsPolicyInput] = useState(DEFAULT_POLICY_VERSION);
  const [analyticsPromptInput, setAnalyticsPromptInput] = useState(DEFAULT_PROMPT_VERSION);
  const [baselineSnapshotId, setBaselineSnapshotId] = useState("");
  const [candidateSnapshotId, setCandidateSnapshotId] = useState("");
  const [driftScoreThreshold, setDriftScoreThreshold] = useState("0.03");
  const [driftOverrideThreshold, setDriftOverrideThreshold] = useState("0.05");

  const [analyticsSnapshots, setAnalyticsSnapshots] = useState<SnapshotItem[]>([]);
  const [analyticsEvaluations, setAnalyticsEvaluations] = useState<EvaluationItem[]>([]);
  const [analyticsTrend, setAnalyticsTrend] = useState<TrendPayload | null>(null);
  const [analyticsComparison, setAnalyticsComparison] = useState<ComparisonPayload | null>(null);

  const [isRefreshingAnalytics, setIsRefreshingAnalytics] = useState(false);
  const [isCreatingSnapshot, setIsCreatingSnapshot] = useState(false);
  const [isRunningSyncJob, setIsRunningSyncJob] = useState(false);
  const [isComparing, setIsComparing] = useState(false);
  const [isRunningDrift, setIsRunningDrift] = useState(false);

  async function refreshAnalyticsEvaluations() {
    const response = await listAnalyticsEvaluations();
    if (!response.ok) {
      throw new Error(`Evaluation request failed with status ${response.status}.`);
    }
    setAnalyticsEvaluations(Array.isArray(response.data) ? (response.data as EvaluationItem[]) : []);
  }

  async function refreshAnalyticsEvaluationTrend() {
    const response = await listAnalyticsTrends();
    if (!response.ok) {
      throw new Error(`Evaluation trend request failed with status ${response.status}.`);
    }
    setAnalyticsTrend((response.data as TrendPayload) ?? null);
  }

  async function refreshAnalyticsSnapshots() {
    setIsRefreshingAnalytics(true);
    setAnalyticsStatusText("Loading analytics snapshots...");

    try {
      const response = await listAnalyticsSnapshots();
      if (!response.ok) {
        throw new Error(`Analytics request failed with status ${response.status}.`);
      }

      const snapshots = Array.isArray(response.data) ? (response.data as SnapshotItem[]) : [];
      setAnalyticsSnapshots(snapshots);

      if (!snapshots.length) {
        setBaselineSnapshotId("");
        setCandidateSnapshotId("");
      } else {
        const hasBaseline = snapshots.some((item) => String(item.snapshot_id) === baselineSnapshotId);
        const hasCandidate = snapshots.some((item) => String(item.snapshot_id) === candidateSnapshotId);

        setBaselineSnapshotId(hasBaseline ? baselineSnapshotId : String(snapshots[snapshots.length - 1].snapshot_id));
        setCandidateSnapshotId(hasCandidate ? candidateSnapshotId : String(snapshots[0].snapshot_id));
      }

      await refreshAnalyticsEvaluations();
      await refreshAnalyticsEvaluationTrend();

      if (!snapshots.length) {
        setAnalyticsStatusText("No snapshots found. Generate one to start tracking analytics history.");
      } else {
        setAnalyticsStatusText(`Loaded ${snapshots.length} analytics snapshot(s).`);
      }
    } catch (error) {
      setAnalyticsStatusText(error instanceof Error ? error.message : "Could not load analytics snapshots.");
    } finally {
      setIsRefreshingAnalytics(false);
    }
  }

  async function onCreateSnapshot() {
    setIsCreatingSnapshot(true);
    setAnalyticsStatusText("Generating analytics snapshot...");
    try {
      const response = await createAnalyticsSnapshot({
        label: analyticsLabelInput.trim(),
        policy_version: analyticsPolicyInput.trim() || DEFAULT_POLICY_VERSION,
        prompt_version: analyticsPromptInput.trim() || DEFAULT_PROMPT_VERSION,
      });

      if (!response.ok) {
        throw new Error(`Snapshot creation failed with status ${response.status}.`);
      }

      const payload = asRecord(response.data);
      setAnalyticsStatusText(`Saved snapshot #${payload?.snapshot_id}.`);
      await refreshAnalyticsSnapshots();
    } catch (error) {
      setAnalyticsStatusText(error instanceof Error ? error.message : "Could not create snapshot.");
    } finally {
      setIsCreatingSnapshot(false);
    }
  }

  async function onRunSnapshotSyncJob() {
    setIsRunningSyncJob(true);
    setAnalyticsStatusText("Running analytics sync job...");

    try {
      const response = await runSnapshotSync({
        label: analyticsLabelInput.trim(),
        policy_version: analyticsPolicyInput.trim() || DEFAULT_POLICY_VERSION,
        prompt_version: analyticsPromptInput.trim() || DEFAULT_PROMPT_VERSION,
      });

      if (!response.ok) {
        throw new Error(`Sync job failed with status ${response.status}.`);
      }

      const payload = asRecord(response.data);
      setAnalyticsStatusText(`Sync job complete. Snapshot #${payload?.snapshot_id} created.`);
      await refreshAnalyticsSnapshots();
    } catch (error) {
      setAnalyticsStatusText(error instanceof Error ? error.message : "Could not run snapshot sync job.");
    } finally {
      setIsRunningSyncJob(false);
    }
  }

  async function onCompareSnapshots() {
    const baselineId = Number(baselineSnapshotId);
    const candidateId = Number(candidateSnapshotId);

    if (!baselineId || !candidateId) {
      setAnalyticsStatusText("Select both baseline and candidate snapshots.");
      return;
    }

    setIsComparing(true);
    setAnalyticsStatusText("Comparing snapshots...");

    try {
      const response = await compareSnapshots(baselineId, candidateId);
      if (!response.ok) {
        throw new Error(`Comparison failed with status ${response.status}.`);
      }

      const payload = asRecord(response.data);
      const comparison = asRecord(payload?.comparison) as unknown as ComparisonPayload;
      setAnalyticsComparison(comparison);
      setAnalyticsStatusText(`Compared snapshot #${baselineId} to #${candidateId}.`);
    } catch (error) {
      setAnalyticsStatusText(error instanceof Error ? error.message : "Could not compare snapshots.");
    } finally {
      setIsComparing(false);
    }
  }

  async function onRunDriftCheck() {
    setIsRunningDrift(true);
    setAnalyticsStatusText("Running drift check...");

    try {
      const response = await runDriftCheck({
        baseline_snapshot_id: Number(baselineSnapshotId) || null,
        candidate_snapshot_id: Number(candidateSnapshotId) || null,
        score_drop_threshold: Number(driftScoreThreshold || 0.03),
        override_increase_threshold: Number(driftOverrideThreshold || 0.05),
      });

      if (!response.ok) {
        throw new Error(`Drift check failed with status ${response.status}.`);
      }

      const payload = asRecord(response.data);
      const comparison = asRecord(payload?.comparison) as unknown as ComparisonPayload;
      setAnalyticsComparison(comparison);
      await refreshAnalyticsEvaluations();
      await refreshAnalyticsEvaluationTrend();
      setAnalyticsStatusText(`Drift check ${payload?.status}. Evaluation #${payload?.evaluation_id} saved.`);
    } catch (error) {
      setAnalyticsStatusText(error instanceof Error ? error.message : "Could not run drift check.");
    } finally {
      setIsRunningDrift(false);
    }
  }

  useEffect(() => {
    void refreshAnalyticsSnapshots();
  }, []);

  return {
    analyticsStatusText,
    analyticsLabelInput,
    analyticsPolicyInput,
    analyticsPromptInput,
    baselineSnapshotId,
    candidateSnapshotId,
    driftScoreThreshold,
    driftOverrideThreshold,
    analyticsSnapshots,
    analyticsEvaluations,
    analyticsTrend,
    analyticsComparison,
    isRefreshingAnalytics,
    isCreatingSnapshot,
    isRunningSyncJob,
    isComparing,
    isRunningDrift,
    setAnalyticsLabelInput,
    setAnalyticsPolicyInput,
    setAnalyticsPromptInput,
    setBaselineSnapshotId,
    setCandidateSnapshotId,
    setDriftScoreThreshold,
    setDriftOverrideThreshold,
    refreshAnalyticsSnapshots,
    onCreateSnapshot,
    onRunSnapshotSyncJob,
    onCompareSnapshots,
    onRunDriftCheck,
  };
}
