export const API_BASE_URL: string;
export function reviewerAuthHeaders(): Record<string, string>;

export function getRunAudit(runId: string): Promise<{ ok: boolean; status: number; data: unknown }>;
export function getReviewQueue(): Promise<{ ok: boolean; status: number; data: unknown }>;
export function submitRunReview(
  runId: string,
  payload: { reviewer_name: string; decision: string; rationale: string }
): Promise<{ ok: boolean; status: number; data: unknown }>;
export function listAnalyticsSnapshots(): Promise<{ ok: boolean; status: number; data: unknown }>;
export function listAnalyticsEvaluations(): Promise<{ ok: boolean; status: number; data: unknown }>;
export function listAnalyticsTrends(): Promise<{ ok: boolean; status: number; data: unknown }>;
export function createAnalyticsSnapshot(payload: {
  label: string;
  policy_version: string;
  prompt_version: string;
}): Promise<{ ok: boolean; status: number; data: unknown }>;
export function runSnapshotSync(payload: {
  label: string;
  policy_version: string;
  prompt_version: string;
}): Promise<{ ok: boolean; status: number; data: unknown }>;
export function compareSnapshots(
  baselineId: number,
  candidateId: number
): Promise<{ ok: boolean; status: number; data: unknown }>;
export function runDriftCheck(payload: {
  baseline_snapshot_id: number | null;
  candidate_snapshot_id: number | null;
  score_drop_threshold: number;
  override_increase_threshold: number;
}): Promise<{ ok: boolean; status: number; data: unknown }>;

export function getFollowUp(runId: string): Promise<{ ok: boolean; status: number; data: unknown }>;
export function saveFollowUp(runId: string, payload: unknown): Promise<{ ok: boolean; status: number; data: unknown }>;
export function updateFollowUp(runId: string, payload: unknown): Promise<{ ok: boolean; status: number; data: unknown }>;
export function generateRecommendationLetter(runId: string, reviewer: string): Promise<{ ok: boolean; status: number; data: unknown }>;
export function downloadAssessmentHtml(runId: string): Promise<{ ok: boolean; status: number; blob: Blob | null }>;
