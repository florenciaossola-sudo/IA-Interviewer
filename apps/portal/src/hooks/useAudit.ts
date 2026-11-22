import { useEffect, useState } from "react";

import { getReviewQueue, getRunAudit, submitRunReview } from "../../legacy/api.js";
import type { AuditBundle, QueueItem } from "../types";
import { asRecord } from "../utils/integrity";

export function useAudit() {
  const [runIdInput, setRunIdInput] = useState("");
  const [statusText, setStatusText] = useState("Enter a run ID to inspect.");
  const [reviewStatusText, setReviewStatusText] = useState("");
  const [auditBundle, setAuditBundle] = useState<AuditBundle | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [queueError, setQueueError] = useState<string | null>(null);

  const [reviewerName, setReviewerName] = useState(
    () => window.localStorage.getItem("ai_interviewer_reviewer") || "reviewer",
  );
  const [decision, setDecision] = useState("approved");
  const [rationale, setRationale] = useState("");

  const [isLoadingAudit, setIsLoadingAudit] = useState(false);
  const [isRefreshingQueue, setIsRefreshingQueue] = useState(false);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);

  async function refreshQueue() {
    setIsRefreshingQueue(true);
    try {
      const response = await getReviewQueue();
      if (!response.ok) {
        throw new Error(`Queue request failed with status ${response.status}.`);
      }

      setQueueItems(Array.isArray(response.data) ? (response.data as QueueItem[]) : []);
      setQueueError(null);
    } catch {
      setQueueItems([]);
      setQueueError("Could not load the review queue.");
    } finally {
      setIsRefreshingQueue(false);
    }
  }

  async function loadAudit(explicitRunId?: string) {
    const runId = (explicitRunId ?? runIdInput).trim();
    if (!runId) {
      setStatusText("Enter a run ID first.");
      return;
    }

    setIsLoadingAudit(true);
  setReviewStatusText("");
  setDecision("approved");
  setRationale("");
    setStatusText(`Loading audit for ${runId}...`);

    try {
      const response = await getRunAudit(runId);
      if (!response.ok) {
        if (response.status === 404) {
          throw new Error("No audit bundle found for that run ID.");
        }
        throw new Error(`Request failed with status ${response.status}.`);
      }

      const data = response.data as AuditBundle;
      setRunIdInput(runId);
      setActiveRunId(runId);
      setAuditBundle(data);
      await refreshQueue();
      setStatusText(`Loaded audit bundle for ${runId}.`);
    } catch (error) {
      setAuditBundle(null);
      setActiveRunId(null);
      setStatusText(error instanceof Error ? error.message : "Could not load audit.");
    } finally {
      setIsLoadingAudit(false);
    }
  }

  async function onSubmitReview(overrideOutcome?: string) {
    if (!activeRunId) {
      setReviewStatusText("Load a run before submitting a review.");
      return;
    }

    const trimmedRationale = rationale.trim();
    if (!trimmedRationale) {
      setReviewStatusText("Rationale is required.");
      return;
    }

    setIsSubmittingReview(true);
    setReviewStatusText("Submitting review...");

    try {
      const response = await submitRunReview(activeRunId, {
        reviewer_name: reviewerName.trim() || "reviewer",
        decision,
        rationale: trimmedRationale,
        ...(decision === "overridden" ? { override_outcome: overrideOutcome } : {}),
      });

      if (!response.ok) {
        const message =
          response.status === 400
            ? "Review requires a valid decision and rationale."
            : `Request failed with status ${response.status}.`;
        throw new Error(message);
      }

      const data = asRecord(response.data);
      const review = asRecord(data?.review);
      const savedOverrideOutcome = typeof review?.override_outcome === "string"
        ? ` (${review.override_outcome})`
        : "";
      setReviewStatusText(`Review saved as ${review?.decision}${savedOverrideOutcome}.`);
      await refreshQueue();
      await loadAudit(activeRunId);
    } catch (error) {
      setReviewStatusText(error instanceof Error ? error.message : "Could not submit review.");
    } finally {
      setIsSubmittingReview(false);
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const preloadedRunId = params.get("run_id");

    if (preloadedRunId) {
      setRunIdInput(preloadedRunId);
      void loadAudit(preloadedRunId);
    }

    void refreshQueue();
  }, []);

  return {
    runIdInput,
    setRunIdInput,
    statusText,
    reviewStatusText,
    auditBundle,
    queueItems,
    queueError,
    reviewerName,
    setReviewerName,
    decision,
    setDecision,
    rationale,
    setRationale,
    isLoadingAudit,
    isRefreshingQueue,
    isSubmittingReview,
    refreshQueue,
    loadAudit,
    onSubmitReview,
  };
}
