from __future__ import annotations

import argparse
import json
import os
from typing import Any

from services.analytics.plane import (
    DEFAULT_POLICY_VERSION,
    DEFAULT_PROMPT_VERSION,
    compare_snapshot_ids,
    save_gold_snapshot,
    snapshot_to_dict,
)
from services.api.persistence import PERSISTENCE

DEFAULT_SCORE_DROP_THRESHOLD = 0.03
DEFAULT_OVERRIDE_INCREASE_THRESHOLD = 0.05
DEFAULT_FAIRNESS_SCORE_DELTA_THRESHOLD = 0.08
DEFAULT_FAIRNESS_OVERRIDE_DELTA_THRESHOLD = 0.1


def run_snapshot_sync_job(
    label: str = "",
    policy_version: str = DEFAULT_POLICY_VERSION,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    persistence: Any = PERSISTENCE,
    integrity_repository: Any | None = None,
) -> dict[str, Any]:
    record = save_gold_snapshot(
        label=label,
        policy_version=policy_version,
        prompt_version=prompt_version,
        persistence=persistence,
        integrity_repository=integrity_repository,
    )
    result = {
        "job_type": "snapshot_sync",
        "status": "completed",
        "snapshot_id": record.snapshot_id,
        "label": record.label,
        "policy_version": record.policy_version,
        "prompt_version": record.prompt_version,
        "created_at": record.created_at,
    }
    if os.getenv("AI_INTERVIEWER_LAKEHOUSE_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }:
        from services.analytics.medallion import materialize_medallion_snapshot

        result["lakehouse"] = materialize_medallion_snapshot(
            record.snapshot_id,
            persistence=persistence,
            integrity_repository=integrity_repository,
        )
    return result


def run_drift_check_job(
    baseline_snapshot_id: int | None = None,
    candidate_snapshot_id: int | None = None,
    score_drop_threshold: float = DEFAULT_SCORE_DROP_THRESHOLD,
    override_increase_threshold: float = DEFAULT_OVERRIDE_INCREASE_THRESHOLD,
    fairness_score_delta_threshold: float = DEFAULT_FAIRNESS_SCORE_DELTA_THRESHOLD,
    fairness_override_delta_threshold: float = DEFAULT_FAIRNESS_OVERRIDE_DELTA_THRESHOLD,
    persistence: Any = PERSISTENCE,
) -> dict[str, Any]:
    resolved_baseline_id, resolved_candidate_id = _resolve_snapshot_pair(
        baseline_snapshot_id=baseline_snapshot_id,
        candidate_snapshot_id=candidate_snapshot_id,
        persistence=persistence,
    )

    comparison = compare_snapshot_ids(
        baseline_snapshot_id=resolved_baseline_id,
        candidate_snapshot_id=resolved_candidate_id,
        persistence=persistence,
    )
    comparison_payload = snapshot_to_dict(comparison)
    llm_trace_rollup = _build_llm_trace_rollup_comparison(
        baseline_snapshot_id=resolved_baseline_id,
        candidate_snapshot_id=resolved_candidate_id,
        persistence=persistence,
    )

    breaches: list[dict[str, Any]] = []
    if comparison.average_score_delta < -score_drop_threshold:
        breaches.append(
            {
                "metric": "average_score_delta",
                "value": comparison.average_score_delta,
                "threshold": -score_drop_threshold,
                "message": "Average score dropped beyond threshold.",
            }
        )

    if comparison.reviewer_override_rate_delta > override_increase_threshold:
        breaches.append(
            {
                "metric": "reviewer_override_rate_delta",
                "value": comparison.reviewer_override_rate_delta,
                "threshold": override_increase_threshold,
                "message": "Reviewer override rate increased beyond threshold.",
            }
        )

    fairness_breaches = _detect_fairness_breaches(
        fairness_slice_deltas=comparison.fairness_slice_deltas,
        score_delta_threshold=fairness_score_delta_threshold,
        override_delta_threshold=fairness_override_delta_threshold,
    )
    breaches.extend(fairness_breaches)

    status = "alert" if breaches else "ok"
    result = {
        "job_type": "drift_check",
        "status": status,
        "baseline_snapshot_id": resolved_baseline_id,
        "candidate_snapshot_id": resolved_candidate_id,
        "thresholds": {
            "score_drop_threshold": score_drop_threshold,
            "override_increase_threshold": override_increase_threshold,
            "fairness_score_delta_threshold": fairness_score_delta_threshold,
            "fairness_override_delta_threshold": fairness_override_delta_threshold,
        },
        "comparison": comparison_payload,
        "breaches": breaches,
        "llm_trace_rollup": llm_trace_rollup,
    }

    evaluation_record = persistence.save_analytics_evaluation(
        evaluation_type="drift_check",
        status=status,
        baseline_snapshot_id=resolved_baseline_id,
        candidate_snapshot_id=resolved_candidate_id,
        thresholds=result["thresholds"],
        result={
            "comparison": comparison_payload,
            "breaches": breaches,
            "llm_trace_rollup": llm_trace_rollup,
        },
        llm_trace_rollup=llm_trace_rollup,
    )

    result["evaluation_id"] = evaluation_record.evaluation_id
    result["evaluated_at"] = evaluation_record.created_at
    return result


def _resolve_snapshot_pair(
    baseline_snapshot_id: int | None,
    candidate_snapshot_id: int | None,
    persistence: Any,
) -> tuple[int, int]:
    if baseline_snapshot_id is not None and candidate_snapshot_id is not None:
        return baseline_snapshot_id, candidate_snapshot_id

    snapshots = persistence.list_analytics_snapshots(limit=2)
    if len(snapshots) < 2:
        raise ValueError("At least two snapshots are required for drift checks")

    candidate = snapshots[0]
    baseline = snapshots[1]
    return baseline.snapshot_id, candidate.snapshot_id


def _detect_fairness_breaches(
    fairness_slice_deltas: list[Any],
    score_delta_threshold: float,
    override_delta_threshold: float,
) -> list[dict[str, Any]]:
    breaches: list[dict[str, Any]] = []
    for item in fairness_slice_deltas:
        if abs(item.average_score) > score_delta_threshold:
            breaches.append(
                {
                    "metric": "fairness_average_score_delta",
                    "slice": item.slice_name,
                    "value": item.average_score,
                    "threshold": score_delta_threshold,
                    "message": "Fairness score delta breached threshold.",
                }
            )

        if abs(item.override_rate) > override_delta_threshold:
            breaches.append(
                {
                    "metric": "fairness_override_rate_delta",
                    "slice": item.slice_name,
                    "value": item.override_rate,
                    "threshold": override_delta_threshold,
                    "message": "Fairness override-rate delta breached threshold.",
                }
            )

    return breaches


def _build_llm_trace_rollup_comparison(
    baseline_snapshot_id: int,
    candidate_snapshot_id: int,
    persistence: Any,
) -> dict[str, Any] | None:
    baseline = persistence.load_analytics_snapshot(baseline_snapshot_id)
    candidate = persistence.load_analytics_snapshot(candidate_snapshot_id)
    if baseline is None or candidate is None:
        return None

    baseline_rollup = _extract_llm_trace_rollup(baseline.payload_json)
    candidate_rollup = _extract_llm_trace_rollup(candidate.payload_json)
    if baseline_rollup is None and candidate_rollup is None:
        return None

    return {
        "baseline": baseline_rollup,
        "candidate": candidate_rollup,
        "fallback_rate_delta": _fallback_rate(candidate_rollup) - _fallback_rate(baseline_rollup),
        "observed_turn_count_delta": _observed_turn_count(candidate_rollup)
        - _observed_turn_count(baseline_rollup),
    }


def _extract_llm_trace_rollup(payload_json: str) -> dict[str, Any] | None:
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        return None
    rollup = payload.get("llm_trace_rollup")
    return rollup if isinstance(rollup, dict) else None


def _fallback_rate(rollup: dict[str, Any] | None) -> float:
    if not isinstance(rollup, dict):
        return 0.0
    value = rollup.get("fallback_rate", 0.0)
    return float(value)


def _observed_turn_count(rollup: dict[str, Any] | None) -> int:
    if not isinstance(rollup, dict):
        return 0
    value = rollup.get("observed_turn_count", 0)
    return int(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 7 analytics scheduler jobs.")
    parser.add_argument(
        "--job",
        choices=["snapshot-sync", "drift-check"],
        required=True,
        help="Job type to execute.",
    )
    parser.add_argument("--label", default="", help="Snapshot label for snapshot-sync job.")
    parser.add_argument("--policy-version", default="unknown")
    parser.add_argument("--prompt-version", default="unknown")
    parser.add_argument("--baseline-id", type=int)
    parser.add_argument("--candidate-id", type=int)
    parser.add_argument("--score-drop-threshold", type=float, default=DEFAULT_SCORE_DROP_THRESHOLD)
    parser.add_argument(
        "--override-increase-threshold",
        type=float,
        default=DEFAULT_OVERRIDE_INCREASE_THRESHOLD,
    )
    parser.add_argument(
        "--fairness-score-delta-threshold",
        type=float,
        default=DEFAULT_FAIRNESS_SCORE_DELTA_THRESHOLD,
    )
    parser.add_argument(
        "--fairness-override-delta-threshold",
        type=float,
        default=DEFAULT_FAIRNESS_OVERRIDE_DELTA_THRESHOLD,
    )
    args = parser.parse_args(argv)

    if args.job == "snapshot-sync":
        output = run_snapshot_sync_job(
            label=args.label,
            policy_version=args.policy_version,
            prompt_version=args.prompt_version,
        )
    else:
        output = run_drift_check_job(
            baseline_snapshot_id=args.baseline_id,
            candidate_snapshot_id=args.candidate_id,
            score_drop_threshold=args.score_drop_threshold,
            override_increase_threshold=args.override_increase_threshold,
            fairness_score_delta_threshold=args.fairness_score_delta_threshold,
            fairness_override_delta_threshold=args.fairness_override_delta_threshold,
        )

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
