from __future__ import annotations

from pathlib import Path

from services.agent.graph.runtime import InterviewGraph
from services.analytics.plane import load_snapshot_from_record
from services.analytics.scheduler import run_drift_check_job, run_snapshot_sync_job
from services.api.interviews import InterviewRepository
from services.api.persistence import RunPersistence


def test_snapshot_sync_and_drift_check_jobs(tmp_path: Path) -> None:
    persistence = RunPersistence(db_path=tmp_path / "scheduler.sqlite3")
    _persist_completed_run(
        persistence=persistence,
        run_id="run-sync-1",
        role="backend_engineer",
        doc_type="role_description",
        answers=[
            "I isolate failures and verify with traces.",
            "I apply backward-compatible API migrations.",
            "I harden CI with deterministic testing.",
        ],
    )
    persistence.save_review_decision(
        run_id="run-sync-1",
        reviewer_name="reviewer.a",
        decision="approved",
        rationale="Baseline run",
    )

    baseline = run_snapshot_sync_job(
        label="baseline",
        policy_version="p7.v2",
        prompt_version="prompt.v1",
        persistence=persistence,
    )
    candidate = run_snapshot_sync_job(
        label="candidate",
        policy_version="p7.v2",
        prompt_version="prompt.v2",
        persistence=persistence,
    )

    result = run_drift_check_job(
        baseline_snapshot_id=int(baseline["snapshot_id"]),
        candidate_snapshot_id=int(candidate["snapshot_id"]),
        persistence=persistence,
    )

    assert result["job_type"] == "drift_check"
    assert result["baseline_snapshot_id"] == baseline["snapshot_id"]
    assert result["candidate_snapshot_id"] == candidate["snapshot_id"]
    assert result["evaluation_id"] > 0
    assert "comparison" in result
    assert "llm_trace_rollup" in result
    assert result["llm_trace_rollup"] is not None

    evaluations = persistence.list_analytics_evaluations(limit=10)
    assert len(evaluations) == 1
    assert evaluations[0].evaluation_type == "drift_check"
    assert evaluations[0].llm_trace_rollup_json is not None


def test_snapshot_sync_exports_integrity_disposition_labels(tmp_path: Path) -> None:
    persistence = RunPersistence(db_path=tmp_path / "scheduler-labels.sqlite3")
    integrity_repository = InterviewRepository(tmp_path / "interviews.sqlite3")
    integrity_repository.save_integrity_disposition(
        "run-labeled",
        "reviewer@example.test",
        "confirmed",
        "Signals were reviewed with supporting evidence.",
    )

    result = run_snapshot_sync_job(
        label="integrity labels",
        persistence=persistence,
        integrity_repository=integrity_repository,
    )
    snapshot = load_snapshot_from_record(int(result["snapshot_id"]), persistence=persistence)

    assert snapshot.integrity_disposition_counts == {"confirmed": 1}
    assert snapshot.integrity_disposition_labels[0].run_id == "run-labeled"


def _persist_completed_run(
    persistence: RunPersistence,
    run_id: str,
    role: str,
    doc_type: str,
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
                "graph_state": {
                    "current_competency": snapshot.current_competency,
                    "current_turn_index": snapshot.current_turn_index,
                    "route_history": snapshot.route_history,
                    "decision_log_tail": [
                        item.to_dict() for item in snapshot.decision_log_tail
                    ],
                    "llm_trace": snapshot.llm_trace,
                },
            },
            checkpoint_index=step.question_index,
            completed=step.completed,
        )
