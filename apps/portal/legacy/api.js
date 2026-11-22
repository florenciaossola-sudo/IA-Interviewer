export const API_BASE_URL = "http://127.0.0.1:8081";

export function reviewerAuthHeaders() {
  const token = window.localStorage.getItem("ai_interviewer_reviewer_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchJson(path, options) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: { ...reviewerAuthHeaders(), ...(options?.headers || {}) },
  });
  return {
    ok: response.ok,
    status: response.status,
    data: response.ok ? await response.json() : null,
  };
}

export async function getRunAudit(runId) {
  return fetchJson(`/runs/${encodeURIComponent(runId)}/audit`);
}

export async function getReviewQueue() {
  return fetchJson("/review/queue");
}

export async function submitRunReview(runId, payload) {
  return fetchJson(`/runs/${encodeURIComponent(runId)}/review`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function getFollowUp(runId) {
  return fetchJson(`/runs/${encodeURIComponent(runId)}/follow-up`);
}

export async function saveFollowUp(runId, payload) {
  return fetchJson(`/runs/${encodeURIComponent(runId)}/follow-up`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateFollowUp(runId, payload) {
  return fetchJson(`/runs/${encodeURIComponent(runId)}/follow-up`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function generateRecommendationLetter(runId, reviewer) {
  return fetchJson(`/runs/${encodeURIComponent(runId)}/recommendation-letter?reviewer=${encodeURIComponent(reviewer)}`, {
    method: "POST",
  });
}

export async function downloadAssessmentHtml(runId) {
  const response = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}/assessment.html`, {
    headers: reviewerAuthHeaders(),
  });
  return { ok: response.ok, status: response.status, blob: response.ok ? await response.blob() : null };
}

export async function listAnalyticsSnapshots() {
  return fetchJson("/analytics/snapshots");
}

export async function listAnalyticsEvaluations() {
  return fetchJson("/analytics/evaluations");
}

export async function listAnalyticsTrends() {
  return fetchJson("/analytics/evaluations/trends");
}

export async function createAnalyticsSnapshot(payload) {
  return fetchJson("/analytics/snapshots", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function runSnapshotSync(payload) {
  return fetchJson("/analytics/jobs/snapshot-sync", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function compareSnapshots(baselineId, candidateId) {
  const url = new URL(`${API_BASE_URL}/analytics/compare`);
  url.searchParams.set("baseline_id", String(baselineId));
  url.searchParams.set("candidate_id", String(candidateId));

  const response = await fetch(url);
  return {
    ok: response.ok,
    status: response.status,
    data: response.ok ? await response.json() : null,
  };
}

export async function runDriftCheck(payload) {
  return fetchJson("/analytics/evaluations/drift-check", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}
