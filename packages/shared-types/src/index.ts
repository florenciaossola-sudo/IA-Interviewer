export type RunStatus =
  | "draft"
  | "ready"
  | "in_progress"
  | "in_review"
  | "finalized";

export interface InterviewRun {
  runId: string;
  status: RunStatus;
}
