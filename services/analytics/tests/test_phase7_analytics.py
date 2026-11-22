from __future__ import annotations

from pathlib import Path

from services.agent.graph.runtime import InterviewGraph
from services.analytics.models import (
    AnalyticsSnapshot,
    FairnessSlice,
    ReviewerOverridePattern,
    RouteDriftPoint,
    ScoreTrendPoint,
)
from services.analytics.plane import (
    build_gold_snapshot,
    compare_snapshots,
    load_snapshot_from_record,
    save_gold_snapshot,
)
from services.api.interviews import InterviewRepository
from services.api.persistence import RunPersistence


def test_build_gold_snapshot_tracks_scores_routes_and_review_patterns(tmp_path: Path) -> None:
    persistence = RunPersistence(db_path=tmp_path / "analytics.sqlite3")
    _persist_run(
        persistence,
        run_id="run-backend",
        role="backend_engineer",
        doc_type="role_description",
        reviewer_name="alex",
        decision="approved",
        answers=[
            "I debug incidents by tracing logs and isolating the failing service.",
            "I keep APIs backward compatible with versioning.",
            "I stabilize flaky tests and watch CI signals.",
        ],
    )
    _persist_run(
        persistence,
        run_id="run-frontend",
        role="frontend_engineer",
        doc_type="engineering_standard",
        reviewer_name="sam",
        decision="overridden",
        answers=[
            "I focus on component boundaries and regressions.",
            "I preserve compatibility with documented contracts.",
            "I fix flaky tests with deterministic waits.",
        ],
    )

    snapshot = build_gold_snapshot(persistence=persistence)

    assert snapshot.run_count == 2
    assert snapshot.completed_run_count == 2
    assert snapshot.turn_count >= 6
    assert snapshot.average_score > 0
    assert snapshot.score_trend
    assert snapshot.route_drift
    assert any(item.slice_name == "role:backend_engineer" for item in snapshot.fairness_slices)
    assert any(
        item.slice_name == "doc_type:engineering_standard"
        for item in snapshot.fairness_slices
    )
    assert any(
        item.reviewer_name == "sam" and item.override_rate == 1.0
        for item in snapshot.reviewer_override_patterns
    )
    assert snapshot.recommendations
    assert snapshot.llm_trace_rollup is not None
    assert snapshot.llm_trace_rollup.observed_turn_count >= 6
    assert snapshot.llm_trace_rollup.provider_counts.get("deterministic", 0) >= 1


def test_compare_snapshots_reports_deltas() -> None:
    baseline = AnalyticsSnapshot(
        generated_at="2026-08-21T00:00:00+00:00",
        run_count=4,
        completed_run_count=3,
        turn_count=10,
        average_score=0.55,
        score_min=0.2,
        score_max=0.9,
        score_buckets={"low": 4, "medium": 4, "high": 2},
        route_distribution={"conclude": 2, "escalate": 1},
        score_trend=[ScoreTrendPoint(date="2026-08-21", sample_count=10, average_score=0.55)],
        route_drift=[
            RouteDriftPoint(
                date="2026-08-21",
                route_distribution={"conclude": 2, "escalate": 1},
            )
        ],
        fairness_slices=[
            FairnessSlice(
                slice_name="role:backend_engineer",
                sample_count=5,
                average_score=0.5,
                override_rate=0.2,
            )
        ],
        reviewer_override_patterns=[
            ReviewerOverridePattern(
                reviewer_name="alex",
                review_count=3,
                override_count=0,
                override_rate=0.0,
            )
        ],
        recommendations=[],
    )
    candidate = AnalyticsSnapshot(
        generated_at="2026-08-22T00:00:00+00:00",
        run_count=5,
        completed_run_count=4,
        turn_count=12,
        average_score=0.68,
        score_min=0.3,
        score_max=0.95,
        score_buckets={"low": 2, "medium": 5, "high": 5},
        route_distribution={"conclude": 4, "escalate": 0},
        score_trend=[ScoreTrendPoint(date="2026-08-22", sample_count=12, average_score=0.68)],
        route_drift=[
            RouteDriftPoint(date="2026-08-22", route_distribution={"conclude": 4})
        ],
        fairness_slices=[
            FairnessSlice(
                slice_name="role:backend_engineer",
                sample_count=6,
                average_score=0.65,
                override_rate=0.1,
            )
        ],
        reviewer_override_patterns=[
            ReviewerOverridePattern(
                reviewer_name="alex",
                review_count=4,
                override_count=1,
                override_rate=0.25,
            )
        ],
        recommendations=[],
    )

    comparison = compare_snapshots(baseline, candidate)

    assert comparison.average_score_delta == 0.13
    assert comparison.completed_run_delta == 1
    assert comparison.reviewer_override_rate_delta == 0.25
    assert comparison.route_distribution_delta["conclude"] == 2
    assert comparison.fairness_slice_deltas[0].slice_name == "role:backend_engineer"


def test_gold_snapshot_exports_integrity_dispositions_as_evaluation_labels(
    tmp_path: Path,
) -> None:
    persistence = RunPersistence(db_path=tmp_path / "analytics.sqlite3")
    integrity_repository = InterviewRepository(tmp_path / "interviews.sqlite3")
    _persist_run(
        persistence,
        run_id="run-labeled",
        role="backend_engineer",
        doc_type="role_description",
        reviewer_name="reviewer@example.test",
        decision="approved",
        answers=["I trace production incidents and isolate the failing service."],
    )
    integrity_repository.save_integrity_disposition(
        "run-labeled",
        "reviewer@example.test",
        "dismissed",
        "The signal has a documented accommodation explanation.",
    )

    record = save_gold_snapshot(
        persistence=persistence,
        integrity_repository=integrity_repository,
    )
    snapshot = load_snapshot_from_record(record.snapshot_id, persistence=persistence)

    assert snapshot.integrity_disposition_counts == {"dismissed": 1}
    assert len(snapshot.integrity_disposition_labels) == 1
    assert snapshot.integrity_disposition_labels[0].run_id == "run-labeled"
    assert snapshot.integrity_disposition_labels[0].disposition == "dismissed"
    assert any(
        item.slice_name == "integrity_disposition:dismissed" and item.sample_count > 0
        for item in snapshot.fairness_slices
    )


def _persist_run(
    persistence: RunPersistence,
    run_id: str,
    role: str,
    doc_type: str,
    reviewer_name: str,
    decision: str,
    answers: list[str],
) -> None:
    graph = InterviewGraph(role=role, doc_type=doc_type)
    first_question = graph.current_question()
    persistence.save_run_start(
        run_id=run_id,
        role=role,
        doc_type=doc_type,
        state=graph.export_state().state,
        payload={
            "run_id": run_id,
            "role": role,
            "doc_type": doc_type,
            "question": first_question,
            "integrity_state": {
                "disclosure_accepted": True,
                "focus_telemetry_enabled": False,
                "suppressed_signal_families": [],
                "telemetry_events": [],
            },
        },
    )

    for answer in answers:
        step = graph.submit_answer(answer)
        snapshot = graph.snapshot()
        persistence.save_turn(
            run_id=run_id,
            role=role,
            doc_type=doc_type,
            state=graph.export_state().state,
            payload={
                "run_id": run_id,
                "role": role,
                "doc_type": doc_type,
                "answer": answer,
                "question": step.question,
                "question_index": step.question_index,
                "completed": step.completed,
                "review_state": {
                    "active_competency": snapshot.current_competency,
                    "turn_index": snapshot.current_turn_index,
                    "completed": step.completed,
                    "decision_summary": snapshot.decision_summary,
                    "route_history": snapshot.route_history,
                    "decision_trail_count": len(snapshot.decision_log_tail),
                },
                "graph_state": {
                    "current_competency": snapshot.current_competency,
                    "current_turn_index": snapshot.current_turn_index,
                    "final_route": snapshot.final_route,
                    "decision_summary": snapshot.decision_summary,
                    "route_history": snapshot.route_history,
                    "decision_log_tail": [item.to_dict() for item in snapshot.decision_log_tail],
                    "llm_trace": snapshot.llm_trace,
                },
            },
            checkpoint_index=step.question_index,
            completed=step.completed,
        )

    persistence.save_review_decision(
        run_id=run_id,
        reviewer_name=reviewer_name,
        decision=decision,
        rationale="Phase 7 analytics test review",
    )