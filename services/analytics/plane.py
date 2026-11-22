from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.analytics.models import (
    AnalyticsComparison,
    AnalyticsSnapshot,
    BronzeDataset,
    BronzeEventRecord,
    BronzeIntegrityDisposition,
    BronzeReviewRecord,
    BronzeRunRecord,
    FairnessSlice,
    IntegrityDispositionLabel,
    LlmTraceRollup,
    ReviewerOverridePattern,
    RouteDriftPoint,
    ScoreTrendPoint,
    TurnScoreSample,
)
from services.api.persistence import PERSISTENCE, AnalyticsSnapshotRecord

SCORE_RE = re.compile(r"score=([0-9]+(?:\.[0-9]+)?)")
DEFAULT_POLICY_VERSION = "adaptive-policy.v1"
DEFAULT_PROMPT_VERSION = "interviewer-prompt.v1"


def collect_bronze(
    persistence: Any = PERSISTENCE,
    integrity_repository: Any | None = None,
) -> BronzeDataset:
    runs = [
        BronzeRunRecord(
            run_id=item.run_id,
            role=item.role,
            doc_type=item.doc_type,
            status=item.status,
            state_json=item.state_json,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in persistence.list_runs()
    ]

    events: list[BronzeEventRecord] = []
    reviews: list[BronzeReviewRecord] = []

    for run in runs:
        events.extend(
            BronzeEventRecord(
                event_id=item.event_id,
                run_id=item.run_id,
                event_type=item.event_type,
                payload=item.payload,
                created_at=item.created_at,
            )
            for item in persistence.load_events(run.run_id)
        )

        review = persistence.load_review_decision(run.run_id)
        if review is not None:
            reviews.append(
                BronzeReviewRecord(
                    review_id=review.review_id,
                    run_id=review.run_id,
                    reviewer_name=review.reviewer_name,
                    decision=review.decision,
                    rationale=review.rationale,
                    created_at=review.created_at,
                    updated_at=review.updated_at,
                )
            )

    integrity_dispositions = []
    if integrity_repository is not None:
        integrity_dispositions = [
            BronzeIntegrityDisposition(
                run_id=item["run_id"],
                reviewer=item["reviewer"],
                disposition=item["disposition"],
                created_at=item["created_at"],
            )
            for item in integrity_repository.list_integrity_dispositions()
        ]

    return BronzeDataset(
        runs=runs,
        events=events,
        reviews=reviews,
        integrity_dispositions=integrity_dispositions,
    )


def build_gold_snapshot(
    bronze: BronzeDataset | None = None,
    persistence: Any = PERSISTENCE,
    integrity_repository: Any | None = None,
) -> AnalyticsSnapshot:
    bronze_dataset = bronze if bronze is not None else collect_bronze(
        persistence=persistence,
        integrity_repository=integrity_repository,
    )
    samples = _build_turn_samples(bronze_dataset.events)
    now = datetime.now(timezone.utc).isoformat()

    score_values = [sample.score for sample in samples]
    route_distribution = Counter(sample.route for sample in samples)
    score_buckets = Counter(_score_bucket(score) for score in score_values)
    score_trend = _score_trend(samples)
    route_drift = _route_drift(samples)
    fairness_slices = _fairness_slices(
        bronze_dataset.runs,
        samples,
        bronze_dataset.reviews,
        bronze_dataset.integrity_dispositions,
    )
    reviewer_override_patterns = _reviewer_override_patterns(bronze_dataset.reviews)
    llm_trace_rollup = _build_llm_trace_rollup(bronze_dataset.events)
    integrity_disposition_counts = dict(
        Counter(item.disposition for item in bronze_dataset.integrity_dispositions)
    )
    integrity_disposition_labels = [
        IntegrityDispositionLabel(
            run_id=item.run_id,
            reviewer=item.reviewer,
            disposition=item.disposition,
            created_at=item.created_at,
        )
        for item in bronze_dataset.integrity_dispositions
    ]

    recommendations = _recommendations(
        average_score=sum(score_values) / len(score_values) if score_values else 0.0,
        override_rate=_override_rate(bronze_dataset.reviews),
        route_distribution=dict(route_distribution),
    )

    return AnalyticsSnapshot(
        generated_at=now,
        run_count=len(bronze_dataset.runs),
        completed_run_count=sum(1 for item in bronze_dataset.runs if item.status in {"in_review", "finalized"}),
        turn_count=len(samples),
        average_score=sum(score_values) / len(score_values) if score_values else 0.0,
        score_min=min(score_values) if score_values else 0.0,
        score_max=max(score_values) if score_values else 0.0,
        score_buckets=dict(score_buckets),
        route_distribution=dict(route_distribution),
        score_trend=score_trend,
        route_drift=route_drift,
        fairness_slices=fairness_slices,
        reviewer_override_patterns=reviewer_override_patterns,
        recommendations=recommendations,
        llm_trace_rollup=llm_trace_rollup,
        integrity_disposition_counts=integrity_disposition_counts,
        integrity_disposition_labels=integrity_disposition_labels,
    )


def compare_snapshots(
    baseline: AnalyticsSnapshot,
    candidate: AnalyticsSnapshot,
) -> AnalyticsComparison:
    route_distribution_delta = _delta_maps(
        baseline.route_distribution,
        candidate.route_distribution,
    )

    baseline_fairness = {item.slice_name: item for item in baseline.fairness_slices}
    candidate_fairness = {item.slice_name: item for item in candidate.fairness_slices}
    fairness_slice_deltas: list[FairnessSlice] = []
    for slice_name in sorted(set(baseline_fairness) | set(candidate_fairness)):
        base_item = baseline_fairness.get(slice_name)
        candidate_item = candidate_fairness.get(slice_name)
        fairness_slice_deltas.append(
            FairnessSlice(
                slice_name=slice_name,
                sample_count=(candidate_item.sample_count if candidate_item else 0)
                - (base_item.sample_count if base_item else 0),
                average_score=(candidate_item.average_score if candidate_item else 0.0)
                - (base_item.average_score if base_item else 0.0),
                override_rate=(candidate_item.override_rate if candidate_item else 0.0)
                - (base_item.override_rate if base_item else 0.0),
            )
        )

    baseline_override_rate = _override_rate_from_patterns(baseline.reviewer_override_patterns)
    candidate_override_rate = _override_rate_from_patterns(candidate.reviewer_override_patterns)

    recommendations = []
    if candidate.average_score > baseline.average_score:
        recommendations.append("Candidate snapshot improved average score.")
    elif candidate.average_score < baseline.average_score:
        recommendations.append("Candidate snapshot decreased average score.")

    if candidate_override_rate > baseline_override_rate:
        recommendations.append("Reviewer overrides increased; inspect policy drift.")

    return AnalyticsComparison(
        baseline_generated_at=baseline.generated_at,
        candidate_generated_at=candidate.generated_at,
        average_score_delta=candidate.average_score - baseline.average_score,
        completed_run_delta=candidate.completed_run_count - baseline.completed_run_count,
        reviewer_override_rate_delta=candidate_override_rate - baseline_override_rate,
        route_distribution_delta=route_distribution_delta,
        fairness_slice_deltas=fairness_slice_deltas,
        recommendations=recommendations,
    )


def save_gold_snapshot(
    label: str = "",
    policy_version: str = DEFAULT_POLICY_VERSION,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    persistence: Any = PERSISTENCE,
    integrity_repository: Any | None = None,
) -> AnalyticsSnapshotRecord:
    snapshot = build_gold_snapshot(
        persistence=persistence,
        integrity_repository=integrity_repository,
    )
    payload = snapshot_to_dict(snapshot)
    return persistence.save_analytics_snapshot(
        payload=payload,
        label=label,
        policy_version=policy_version,
        prompt_version=prompt_version,
    )


def load_snapshot_from_record(
    snapshot_id: int,
    persistence: Any = PERSISTENCE,
) -> AnalyticsSnapshot:
    record = persistence.load_analytics_snapshot(snapshot_id)
    if record is None:
        raise ValueError(f"Snapshot not found: {snapshot_id}")

    payload = json.loads(record.payload_json)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid snapshot payload for snapshot {snapshot_id}")

    return _snapshot_from_dict(payload)


def compare_snapshot_ids(
    baseline_snapshot_id: int,
    candidate_snapshot_id: int,
    persistence: Any = PERSISTENCE,
) -> AnalyticsComparison:
    baseline = load_snapshot_from_record(baseline_snapshot_id, persistence=persistence)
    candidate = load_snapshot_from_record(candidate_snapshot_id, persistence=persistence)
    return compare_snapshots(baseline=baseline, candidate=candidate)


def snapshot_to_dict(snapshot: AnalyticsSnapshot | AnalyticsComparison) -> dict[str, Any]:
    return asdict(snapshot)


def load_snapshot_file(path: Path) -> AnalyticsSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _snapshot_from_dict(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Phase 7 analytics snapshots.")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON output.")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Persist the generated snapshot in SQLite.",
    )
    parser.add_argument("--label", default="", help="Optional snapshot label when using --save.")
    parser.add_argument(
        "--policy-version",
        default="unknown",
        help="Policy version metadata used when saving snapshots.",
    )
    parser.add_argument(
        "--prompt-version",
        default="unknown",
        help="Prompt version metadata used when saving snapshots.",
    )
    parser.add_argument(
        "--compare-to",
        type=Path,
        help="Compare the current database snapshot to a saved baseline snapshot JSON file.",
    )
    parser.add_argument(
        "--compare-baseline-id",
        type=int,
        help="Compare two persisted snapshots by baseline snapshot ID.",
    )
    parser.add_argument(
        "--compare-candidate-id",
        type=int,
        help="Compare two persisted snapshots by candidate snapshot ID.",
    )
    args = parser.parse_args(argv)

    if args.compare_to and args.save:
        raise ValueError("Use either --save or --compare-to, not both")

    if args.compare_to and (
        args.compare_baseline_id is not None or args.compare_candidate_id is not None
    ):
        raise ValueError("Use either --compare-to or --compare-*-id, not both")

    if (args.compare_baseline_id is None) ^ (args.compare_candidate_id is None):
        raise ValueError("Both --compare-baseline-id and --compare-candidate-id are required")

    if args.compare_baseline_id is not None and args.compare_candidate_id is not None:
        comparison = compare_snapshot_ids(
            baseline_snapshot_id=args.compare_baseline_id,
            candidate_snapshot_id=args.compare_candidate_id,
        )
        output = snapshot_to_dict(comparison)
    else:
        snapshot = build_gold_snapshot()
        if args.save:
            saved = PERSISTENCE.save_analytics_snapshot(
                payload=snapshot_to_dict(snapshot),
                label=args.label,
                policy_version=args.policy_version,
                prompt_version=args.prompt_version,
            )
            output = {
                "snapshot_id": saved.snapshot_id,
                "label": saved.label,
                "policy_version": saved.policy_version,
                "prompt_version": saved.prompt_version,
                "created_at": saved.created_at,
                "snapshot": snapshot_to_dict(snapshot),
            }
        elif args.compare_to:
            baseline = load_snapshot_file(args.compare_to)
            comparison = compare_snapshots(baseline, snapshot)
            output = snapshot_to_dict(comparison)
        else:
            output = snapshot_to_dict(snapshot)

    print(json.dumps(output, indent=2, sort_keys=True))

    return 0


def _build_turn_samples(events: list[BronzeEventRecord]) -> list[TurnScoreSample]:
    samples: list[TurnScoreSample] = []
    for event in events:
        graph_state = event.payload.get("graph_state")
        if not isinstance(graph_state, dict):
            continue

        route_history = graph_state.get("route_history") or []
        if not isinstance(route_history, list) or not route_history:
            continue

        route = str(route_history[-1])
        decision_tail = graph_state.get("decision_log_tail") or []
        score = _extract_score(decision_tail)
        if score is None:
            continue

        samples.append(
            TurnScoreSample(
                run_id=event.run_id,
                role=str(event.payload.get("role", "unknown")),
                doc_type=str(event.payload.get("doc_type", "unknown")),
                created_at=event.created_at,
                route=route,
                score=score,
            )
        )

    return samples


def _extract_score(decision_tail: Any) -> float | None:
    if not isinstance(decision_tail, list):
        return None

    for item in decision_tail:
        if not isinstance(item, dict):
            continue
        if item.get("node") != "decide":
            continue
        reason = item.get("reason")
        if not isinstance(reason, str):
            continue
        match = SCORE_RE.search(reason)
        if match:
            return float(match.group(1))

    return None


def _score_bucket(score: float) -> str:
    if score < 0.5:
        return "low"
    if score < 0.8:
        return "medium"
    return "high"


def _score_trend(samples: list[TurnScoreSample]) -> list[ScoreTrendPoint]:
    by_date: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        by_date[sample.created_at[:10]].append(sample.score)

    return [
        ScoreTrendPoint(
            date=date,
            sample_count=len(values),
            average_score=sum(values) / len(values),
        )
        for date, values in sorted(by_date.items())
    ]


def _route_drift(samples: list[TurnScoreSample]) -> list[RouteDriftPoint]:
    by_date: dict[str, Counter[str]] = defaultdict(Counter)
    for sample in samples:
        by_date[sample.created_at[:10]][sample.route] += 1

    return [
        RouteDriftPoint(date=date, route_distribution=dict(counter))
        for date, counter in sorted(by_date.items())
    ]


def _fairness_slices(
    runs: list[BronzeRunRecord],
    samples: list[TurnScoreSample],
    reviews: list[BronzeReviewRecord],
    integrity_dispositions: list[BronzeIntegrityDisposition] | None = None,
) -> list[FairnessSlice]:
    run_lookup = {item.run_id: item for item in runs}
    slices: list[FairnessSlice] = []

    for key_selector in (lambda run: f"role:{run.role}", lambda run: f"doc_type:{run.doc_type}"):
        grouped_scores: dict[str, list[float]] = defaultdict(list)
        grouped_reviews: dict[str, list[str]] = defaultdict(list)

        for sample in samples:
            run = run_lookup.get(sample.run_id)
            if run is None:
                continue
            grouped_scores[key_selector(run)].append(sample.score)

        for review in reviews:
            run = run_lookup.get(review.run_id)
            if run is None:
                continue
            grouped_reviews[key_selector(run)].append(review.decision)

        for slice_name in sorted(grouped_scores):
            decisions = grouped_reviews.get(slice_name, [])
            slices.append(
                FairnessSlice(
                    slice_name=slice_name,
                    sample_count=len(grouped_scores[slice_name]),
                    average_score=sum(grouped_scores[slice_name])
                    / len(grouped_scores[slice_name]),
                    override_rate=(decisions.count("overridden") / len(decisions))
                    if decisions
                    else 0.0,
                )
            )

    run_dispositions = {
        item.run_id: item.disposition for item in integrity_dispositions or []
    }
    disposition_scores: dict[str, list[float]] = defaultdict(list)
    disposition_reviews: dict[str, list[str]] = defaultdict(list)
    for sample in samples:
        disposition = run_dispositions.get(sample.run_id)
        if disposition is not None:
            disposition_scores[disposition].append(sample.score)
    for review in reviews:
        disposition = run_dispositions.get(review.run_id)
        if disposition is not None:
            disposition_reviews[disposition].append(review.decision)

    for disposition in sorted(disposition_scores):
        decisions = disposition_reviews.get(disposition, [])
        scores = disposition_scores[disposition]
        slices.append(
            FairnessSlice(
                slice_name=f"integrity_disposition:{disposition}",
                sample_count=len(scores),
                average_score=sum(scores) / len(scores),
                override_rate=(decisions.count("overridden") / len(decisions))
                if decisions
                else 0.0,
            )
        )

    return slices


def _reviewer_override_patterns(reviews: list[BronzeReviewRecord]) -> list[ReviewerOverridePattern]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for review in reviews:
        grouped[review.reviewer_name].append(review.decision)

    return [
        ReviewerOverridePattern(
            reviewer_name=reviewer_name,
            review_count=len(decisions),
            override_count=decisions.count("overridden"),
            override_rate=decisions.count("overridden") / len(decisions) if decisions else 0.0,
        )
        for reviewer_name, decisions in sorted(grouped.items())
    ]


def _override_rate(reviews: list[BronzeReviewRecord]) -> float:
    if not reviews:
        return 0.0
    return sum(1 for item in reviews if item.decision == "overridden") / len(reviews)


def _override_rate_from_patterns(patterns: list[ReviewerOverridePattern]) -> float:
    if not patterns:
        return 0.0
    total_reviews = sum(item.review_count for item in patterns)
    total_overrides = sum(item.override_count for item in patterns)
    return total_overrides / total_reviews if total_reviews else 0.0


def _recommendations(
    average_score: float,
    override_rate: float,
    route_distribution: dict[str, int],
) -> list[str]:
    recommendations: list[str] = []
    if average_score < 0.6:
        recommendations.append("Average score is low; review prompt and retrieval quality.")
    if override_rate > 0.25:
        recommendations.append("Reviewer override rate is elevated; inspect the human gate.")
    if route_distribution.get("escalate", 0) > route_distribution.get("conclude", 0):
        recommendations.append("Escalations exceed conclusions; inspect route policy drift.")
    return recommendations


def _build_llm_trace_rollup(events: list[BronzeEventRecord]) -> LlmTraceRollup | None:
    provider_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    observed_turn_count = 0
    fallback_used_count = 0

    for event in events:
        graph_state = event.payload.get("graph_state")
        if not isinstance(graph_state, dict):
            continue

        llm_trace = graph_state.get("llm_trace")
        if not isinstance(llm_trace, dict):
            continue

        observed_turn_count += 1
        provider = llm_trace.get("provider")
        if isinstance(provider, str) and provider.strip():
            provider_counts[provider.strip()] += 1

        model = llm_trace.get("model")
        if isinstance(model, str) and model.strip():
            model_counts[model.strip()] += 1

        if llm_trace.get("fallback_used") is True:
            fallback_used_count += 1

    if observed_turn_count == 0:
        return None

    return LlmTraceRollup(
        observed_turn_count=observed_turn_count,
        fallback_used_count=fallback_used_count,
        fallback_rate=fallback_used_count / observed_turn_count,
        provider_counts=dict(provider_counts),
        model_counts=dict(model_counts),
    )


def _delta_maps(baseline: dict[str, int], candidate: dict[str, int]) -> dict[str, int]:
    keys = set(baseline) | set(candidate)
    return {key: candidate.get(key, 0) - baseline.get(key, 0) for key in sorted(keys)}


def _snapshot_from_dict(payload: dict[str, Any]) -> AnalyticsSnapshot:
    llm_trace_rollup_payload = payload.get("llm_trace_rollup")
    llm_trace_rollup: LlmTraceRollup | None = None
    if isinstance(llm_trace_rollup_payload, dict):
        llm_trace_rollup = LlmTraceRollup(
            observed_turn_count=int(llm_trace_rollup_payload.get("observed_turn_count", 0)),
            fallback_used_count=int(llm_trace_rollup_payload.get("fallback_used_count", 0)),
            fallback_rate=float(llm_trace_rollup_payload.get("fallback_rate", 0.0)),
            provider_counts={
                str(key): int(value)
                for key, value in llm_trace_rollup_payload.get("provider_counts", {}).items()
            },
            model_counts={
                str(key): int(value)
                for key, value in llm_trace_rollup_payload.get("model_counts", {}).items()
            },
        )

    return AnalyticsSnapshot(
        generated_at=str(payload["generated_at"]),
        run_count=int(payload["run_count"]),
        completed_run_count=int(payload["completed_run_count"]),
        turn_count=int(payload["turn_count"]),
        average_score=float(payload["average_score"]),
        score_min=float(payload["score_min"]),
        score_max=float(payload["score_max"]),
        score_buckets={str(key): int(value) for key, value in payload["score_buckets"].items()},
        route_distribution={
            str(key): int(value) for key, value in payload["route_distribution"].items()
        },
        score_trend=[
            ScoreTrendPoint(
                date=str(item["date"]),
                sample_count=int(item["sample_count"]),
                average_score=float(item["average_score"]),
            )
            for item in payload["score_trend"]
        ],
        route_drift=[
            RouteDriftPoint(
                date=str(item["date"]),
                route_distribution={
                    str(key): int(value)
                    for key, value in item["route_distribution"].items()
                },
            )
            for item in payload["route_drift"]
        ],
        fairness_slices=[
            FairnessSlice(
                slice_name=str(item["slice_name"]),
                sample_count=int(item["sample_count"]),
                average_score=float(item["average_score"]),
                override_rate=float(item["override_rate"]),
            )
            for item in payload["fairness_slices"]
        ],
        reviewer_override_patterns=[
            ReviewerOverridePattern(
                reviewer_name=str(item["reviewer_name"]),
                review_count=int(item["review_count"]),
                override_count=int(item["override_count"]),
                override_rate=float(item["override_rate"]),
            )
            for item in payload["reviewer_override_patterns"]
        ],
        recommendations=[str(item) for item in payload["recommendations"]],
        llm_trace_rollup=llm_trace_rollup,
        integrity_disposition_counts={
            str(key): int(value)
            for key, value in payload.get("integrity_disposition_counts", {}).items()
        },
        integrity_disposition_labels=[
            IntegrityDispositionLabel(
                run_id=str(item["run_id"]),
                reviewer=str(item["reviewer"]),
                disposition=str(item["disposition"]),
                created_at=str(item["created_at"]),
            )
            for item in payload.get("integrity_disposition_labels", [])
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())