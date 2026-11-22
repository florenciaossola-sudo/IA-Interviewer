export type RunRecord = {
  run_id: string;
  status: string;
  role: string;
  doc_type: string;
  created_at: string;
  updated_at: string;
};

export type EventRecord = {
  event_id: number;
  event_type: string;
  created_at: string;
  payload: Record<string, unknown>;
};

export type CheckpointRecord = {
  checkpoint_id: number;
  checkpoint_index: number;
  created_at: string;
  state: Record<string, unknown>;
};

export type AuditBundle = {
  run: RunRecord;
  events: EventRecord[];
  checkpoints: CheckpointRecord[];
};

export type ReviewStateSnapshot = {
  competency_coverage?: number;
  competency_coverage_target?: number;
  competency_coverage_met?: boolean;
  cumulative_confidence?: number;
  cumulative_confidence_target?: number;
  cumulative_confidence_met?: boolean;
  safety_turn_limit?: number;
  safety_turn_limit_reached?: boolean;
  off_topic_count?: number;
};

export type GraphStateSnapshot = {
  final_route?: string | null;
  evaluated_turns?: number;
  max_turns?: number;
  remaining_competencies?: number;
  total_competencies?: number;
  confidence_average?: number;
  decision_log_tail?: DecisionLogItem[];
};

export type DecisionLogItem = {
  node: string;
  route: string;
  reason: string;
  alternatives?: string[];
};

export type QueueItem = {
  run_id: string;
  role: string;
  doc_type: string;
  updated_at: string;
  aai_index: number | null;
  review_priority_score: number | null;
  priority_band: "none" | "low" | "elevated" | "high" | "unknown";
  priority_reasons: string[];
  assigned_reviewer?: string;
};

export type SnapshotItem = {
  snapshot_id: number;
  label: string | null;
  policy_version: string;
  prompt_version: string;
  created_at: string;
};

export type EvaluationItem = {
  evaluation_id: number;
  baseline_snapshot_id: number | null;
  candidate_snapshot_id: number | null;
  status: string;
  created_at: string;
};

export type TrendPoint = {
  evaluation_id: number;
  status: string;
  baseline_fallback_rate: number;
  candidate_fallback_rate: number;
  fallback_rate_delta: number;
  observed_turn_count_delta: number;
  created_at: string;
};

export type TrendPayload = {
  average_candidate_fallback_rate: number;
  average_fallback_rate_delta: number;
  max_candidate_fallback_rate: number;
  points: TrendPoint[];
};

export type ComparisonPayload = {
  average_score_delta: number;
  completed_run_delta: number;
  reviewer_override_rate_delta: number;
  route_distribution_delta: Record<string, number>;
  fairness_slice_deltas: unknown[];
  recommendations: string[];
};

export type IntegritySignal = {
  signal_family: string;
  event_count: number;
  suppressed?: boolean;
  evidence: string[];
};

export type IntegrityState = {
  aai_index: number;
  disposition: string;
  signal_breakdown: IntegritySignal[];
  confounders: string[];
  baseline_available?: boolean;
  baseline_answer_length?: number | null;
  current_answer_length?: number | null;
  baseline_deviation_ratio?: number | null;
};

export type FollowUp = {
  run_id: string;
  reviewer: string;
  requested_action: string;
  status: "requested" | "in_progress" | "completed" | "cancelled";
  note: string;
  created_at: string;
  updated_at: string;
};
