from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.api import main as api_main


def test_analytics_snapshot_and_compare_endpoints(tmp_path: Path) -> None:
    api_main.RUN_STATE.clear()
    api_main.PERSISTENCE._db_path = tmp_path / "ai_interviewer.sqlite3"  # type: ignore[attr-defined]
    api_main.PERSISTENCE.ensure_schema()

    client = TestClient(api_main.app)
    run_id = _create_completed_run(client)

    review_response = client.post(
        f"/runs/{run_id}/review",
        json={
            "reviewer_name": "alex.reviewer",
            "decision": "approved",
            "rationale": "Completed with clear evidence.",
        },
    )
    assert review_response.status_code == 200

    first_snapshot = client.post(
        "/analytics/snapshots",
        json={
            "label": "baseline",
            "policy_version": "p7.v1",
            "prompt_version": "prompt.v1",
        },
    )
    assert first_snapshot.status_code == 200
    first_payload = first_snapshot.json()
    first_id = first_payload["snapshot_id"]
    assert first_payload["label"] == "baseline"
    assert first_payload["snapshot"]["run_count"] >= 1
    assert first_payload["llm_trace_rollup"] is not None
    assert first_payload["llm_trace_rollup"]["observed_turn_count"] >= 1

    second_snapshot = client.post(
        "/analytics/snapshots",
        json={
            "label": "candidate",
            "policy_version": "p7.v1",
            "prompt_version": "prompt.v2",
        },
    )
    assert second_snapshot.status_code == 200
    second_payload = second_snapshot.json()
    second_id = second_payload["snapshot_id"]

    list_response = client.get("/analytics/snapshots")
    assert list_response.status_code == 200
    listed_ids = [item["snapshot_id"] for item in list_response.json()]
    assert first_id in listed_ids
    assert second_id in listed_ids

    detail_response = client.get(f"/analytics/snapshots/{first_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["snapshot_id"] == first_id
    assert detail_payload["snapshot"]["generated_at"]
    assert detail_payload["llm_trace_rollup"] is not None

    compare_response = client.get(
        "/analytics/compare",
        params={"baseline_id": first_id, "candidate_id": second_id},
    )
    assert compare_response.status_code == 200
    compare_payload = compare_response.json()
    assert compare_payload["baseline_snapshot_id"] == first_id
    assert compare_payload["candidate_snapshot_id"] == second_id
    assert "average_score_delta" in compare_payload["comparison"]


def test_analytics_scheduler_and_evaluation_endpoints(tmp_path: Path) -> None:
    api_main.RUN_STATE.clear()
    api_main.PERSISTENCE._db_path = tmp_path / "ai_interviewer.sqlite3"  # type: ignore[attr-defined]
    api_main.PERSISTENCE.ensure_schema()

    client = TestClient(api_main.app)
    run_id = _create_completed_run(client)

    review_response = client.post(
        f"/runs/{run_id}/review",
        json={
            "reviewer_name": "alex.reviewer",
            "decision": "approved",
            "rationale": "Completed with clear evidence.",
        },
    )
    assert review_response.status_code == 200

    first_sync = client.post(
        "/analytics/jobs/snapshot-sync",
        json={
            "label": "baseline-sync",
            "policy_version": "p7.v2",
            "prompt_version": "prompt.v2",
        },
    )
    assert first_sync.status_code == 200
    first_id = first_sync.json()["snapshot_id"]

    second_sync = client.post(
        "/analytics/jobs/snapshot-sync",
        json={
            "label": "candidate-sync",
            "policy_version": "p7.v2",
            "prompt_version": "prompt.v3",
        },
    )
    assert second_sync.status_code == 200
    second_id = second_sync.json()["snapshot_id"]

    drift_response = client.post(
        "/analytics/evaluations/drift-check",
        json={
            "baseline_snapshot_id": first_id,
            "candidate_snapshot_id": second_id,
            "score_drop_threshold": 0.03,
            "override_increase_threshold": 0.05,
        },
    )
    assert drift_response.status_code == 200
    drift_payload = drift_response.json()
    assert drift_payload["evaluation_id"] > 0
    assert drift_payload["baseline_snapshot_id"] == first_id
    assert drift_payload["candidate_snapshot_id"] == second_id
    assert "comparison" in drift_payload
    assert "breaches" in drift_payload
    assert drift_payload["llm_trace_rollup"] is not None

    evaluations_response = client.get("/analytics/evaluations")
    assert evaluations_response.status_code == 200
    evaluations = evaluations_response.json()
    assert evaluations
    assert evaluations[0]["evaluation_type"] == "drift_check"

    evaluation_id = drift_payload["evaluation_id"]
    evaluation_detail = client.get(f"/analytics/evaluations/{evaluation_id}")
    assert evaluation_detail.status_code == 200
    detail_payload = evaluation_detail.json()
    assert detail_payload["evaluation_id"] == evaluation_id
    assert "comparison" in detail_payload["result"]
    assert detail_payload["llm_trace_rollup"] is not None

    trends_response = client.get("/analytics/evaluations/trends")
    assert trends_response.status_code == 200
    trends_payload = trends_response.json()
    assert trends_payload["evaluation_count"] >= 1
    assert trends_payload["points"]
    assert trends_payload["points"][0]["evaluation_id"] == evaluation_id
    assert "candidate_fallback_rate" in trends_payload["points"][0]


def test_analytics_trends_include_partial_llm_rollup(tmp_path: Path) -> None:
    api_main.RUN_STATE.clear()
    api_main.PERSISTENCE._db_path = tmp_path / "ai_interviewer.sqlite3"  # type: ignore[attr-defined]
    api_main.PERSISTENCE.ensure_schema()

    rollup = {
        "baseline": None,
        "candidate": {
            "observed_turn_count": 5,
            "fallback_used_count": 1,
            "fallback_rate": 0.2,
            "provider_counts": {"deterministic": 5},
            "model_counts": {"local-evaluator": 5},
        },
        "fallback_rate_delta": 0.2,
        "observed_turn_count_delta": 5,
    }

    api_main.PERSISTENCE.save_analytics_evaluation(
        evaluation_type="drift_check",
        status="alert",
        thresholds={"score_drop_threshold": 0.03},
        result={"comparison": {}, "breaches": [], "llm_trace_rollup": rollup},
        baseline_snapshot_id=1,
        candidate_snapshot_id=2,
        llm_trace_rollup=rollup,
    )

    client = TestClient(api_main.app)
    trends_response = client.get("/analytics/evaluations/trends")
    assert trends_response.status_code == 200
    trends_payload = trends_response.json()

    assert trends_payload["evaluation_count"] == 1
    assert len(trends_payload["points"]) == 1
    assert trends_payload["points"][0]["baseline_fallback_rate"] == 0.0
    assert trends_payload["points"][0]["candidate_fallback_rate"] == 0.2
    assert trends_payload["points"][0]["fallback_rate_delta"] == 0.2


def _create_completed_run(client: TestClient) -> str:
    start_response = client.post(
        "/run/start",
        json={"role": "backend_engineer", "doc_type": "role_description"},
    )
    assert start_response.status_code == 200
    run_id = start_response.json()["run_id"]

    warmup_response = client.post(
        "/run/answer",
        json={"run_id": run_id, "answer": "I recently improved a service reliability problem."},
    )
    assert warmup_response.status_code == 200

    answers = [
        "I isolate failing systems and use traces to converge quickly.",
        "I ship API changes with explicit versioning and migration guides.",
        "I stabilize flaky CI with deterministic test harnesses.",
        "I investigate regressions with reproducible test cases.",
        "I debug production incidents and monitor the rollout after release.",
    ]
    completed = False
    for answer in answers:
        response = client.post(
            "/run/answer",
            json={"run_id": run_id, "answer": answer},
        )
        assert response.status_code == 200
        completed = response.json()["completed"]
        if completed:
            break

    assert completed is True

    return run_id
