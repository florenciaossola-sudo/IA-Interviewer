from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BronzeRunRecord:
    run_id: str
    role: str
    doc_type: str
    status: str
    state_json: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class BronzeEventRecord:
    event_id: int
    run_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class BronzeReviewRecord:
    review_id: int
    run_id: str
    reviewer_name: str
    decision: str
    rationale: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class BronzeIntegrityDisposition:
    run_id: str
    reviewer: str
    disposition: str
    created_at: str


@dataclass(frozen=True)
class BronzeDataset:
    runs: list[BronzeRunRecord] = field(default_factory=list)
    events: list[BronzeEventRecord] = field(default_factory=list)
    reviews: list[BronzeReviewRecord] = field(default_factory=list)
    integrity_dispositions: list[BronzeIntegrityDisposition] = field(default_factory=list)


@dataclass(frozen=True)
class TurnScoreSample:
    run_id: str
    role: str
    doc_type: str
    created_at: str
    route: str
    score: float


@dataclass(frozen=True)
class ReviewerOverridePattern:
    reviewer_name: str
    review_count: int
    override_count: int
    override_rate: float


@dataclass(frozen=True)
class FairnessSlice:
    slice_name: str
    sample_count: int
    average_score: float
    override_rate: float


@dataclass(frozen=True)
class ScoreTrendPoint:
    date: str
    sample_count: int
    average_score: float


@dataclass(frozen=True)
class RouteDriftPoint:
    date: str
    route_distribution: dict[str, int]


@dataclass(frozen=True)
class LlmTraceRollup:
    observed_turn_count: int
    fallback_used_count: int
    fallback_rate: float
    provider_counts: dict[str, int]
    model_counts: dict[str, int]


@dataclass(frozen=True)
class IntegrityDispositionLabel:
    run_id: str
    reviewer: str
    disposition: str
    created_at: str


@dataclass(frozen=True)
class AnalyticsSnapshot:
    generated_at: str
    run_count: int
    completed_run_count: int
    turn_count: int
    average_score: float
    score_min: float
    score_max: float
    score_buckets: dict[str, int]
    route_distribution: dict[str, int]
    score_trend: list[ScoreTrendPoint]
    route_drift: list[RouteDriftPoint]
    fairness_slices: list[FairnessSlice]
    reviewer_override_patterns: list[ReviewerOverridePattern]
    recommendations: list[str]
    llm_trace_rollup: LlmTraceRollup | None = None
    integrity_disposition_counts: dict[str, int] = field(default_factory=dict)
    integrity_disposition_labels: list[IntegrityDispositionLabel] = field(default_factory=list)


@dataclass(frozen=True)
class AnalyticsComparison:
    baseline_generated_at: str
    candidate_generated_at: str
    average_score_delta: float
    completed_run_delta: int
    reviewer_override_rate_delta: float
    route_distribution_delta: dict[str, int]
    fairness_slice_deltas: list[FairnessSlice]
    recommendations: list[str]