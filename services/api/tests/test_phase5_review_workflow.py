from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.api import main as api_main


def test_review_queue_and_decision_flow(tmp_path: Path) -> None:
    api_main.RUN_STATE.clear()
    api_main.PERSISTENCE._db_path = tmp_path / "ai_interviewer.sqlite3"  # type: ignore[attr-defined]
    api_main.PERSISTENCE.ensure_schema()

    client = TestClient(api_main.app)

    start_response = client.post(
        "/run/start", json={"role": "backend_engineer", "doc_type": "role_description"}
    )
    assert start_response.status_code == 200
    run_id = start_response.json()["run_id"]

    warmup_response = client.post(
        "/run/answer",
        json={"run_id": run_id, "answer": "I recently improved a service reliability problem."},
    )
    assert warmup_response.status_code == 200

    answers = [
        "I isolate the failing layer, reproduce it, and check the traces.",
        "I preserve backward compatibility by versioning carefully.",
        "I remove flaky tests and stabilize CI signals.",
    ]

    for answer in answers:
        response = client.post(
            "/run/answer",
            json={"run_id": run_id, "answer": answer},
        )
        assert response.status_code == 200

    queue_response = client.get("/review/queue")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert [item["run_id"] for item in queue_payload] == [run_id]

    review_response = client.post(
        f"/runs/{run_id}/review",
        json={
            "reviewer_name": "alex.reviewer",
            "decision": "approved",
            "rationale": "The transcript shows enough evidence and a clean final route.",
        },
    )
    assert review_response.status_code == 200
    review_payload = review_response.json()
    assert review_payload["review"]["run_id"] == run_id
    assert review_payload["review"]["decision"] == "approved"
    assert review_payload["run"]["status"] == "finalized"

    queue_after_review = client.get("/review/queue")
    assert queue_after_review.status_code == 200
    assert queue_after_review.json() == []

    audit_response = client.get(f"/runs/{run_id}/audit")
    assert audit_response.status_code == 200
    assert audit_response.json()["run"]["run_id"] == run_id

    missing_outcome = client.post(
        f"/runs/{run_id}/review",
        json={
            "reviewer_name": "alex.reviewer",
            "decision": "overridden",
            "rationale": "The evidence supports a different outcome.",
        },
    )
    assert missing_outcome.status_code == 400

    override_response = client.post(
        f"/runs/{run_id}/review",
        json={
            "reviewer_name": "alex.reviewer",
            "decision": "overridden",
            "override_outcome": "conclude",
            "rationale": "The evidence supports a conclusion instead of escalation.",
        },
    )
    assert override_response.status_code == 409, override_response.text


def test_review_queue_prioritizes_integrity_anomaly_signals(tmp_path: Path) -> None:
    api_main.RUN_STATE.clear()
    api_main.PERSISTENCE._db_path = tmp_path / "priority.sqlite3"  # type: ignore[attr-defined]
    api_main.PERSISTENCE.ensure_schema()
    client = TestClient(api_main.app)

    for run_id, aai_index, event_count in (
        ("iv_low_priority", 10, 2),
        ("iv_high_priority", 75, 15),
    ):
        api_main.PERSISTENCE.save_run_start(
            run_id=run_id,
            role="backend_engineer",
            doc_type="role_description",
            state={"final_route": "conclude"},
            payload={"run_id": run_id},
        )
        api_main.PERSISTENCE.save_turn(
            run_id=run_id,
            role="backend_engineer",
            doc_type="role_description",
            state={"final_route": "conclude"},
            payload={
                "integrity_state": {
                    "aai_index": aai_index,
                    "signal_breakdown": [
                        {"signal_family": "timing", "event_count": event_count, "suppressed": False}
                    ],
                }
            },
            checkpoint_index=1,
            completed=True,
        )

    response = client.get("/review/queue")

    assert response.status_code == 200
    items = response.json()
    assert [item["run_id"] for item in items] == ["iv_high_priority", "iv_low_priority"]
    assert items[0]["review_priority_score"] == 75
    assert items[0]["priority_band"] == "high"
    assert items[0]["priority_reasons"] == ["timing: 15"]