from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.agent.graph import studio_graph
from services.agent.graph.checkpointing import close_checkpointed_graph
from services.agent.graph.llm import LlmAdapterError, LlmTurnAssessment
from services.api import main as api_main


def test_evaluation_trace_is_saved_for_each_turn(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_INTERVIEWER_DB_BACKEND", "sqlite")
    monkeypatch.setenv("AI_INTERVIEWER_QUESTION_LLM_ENABLED", "0")
    monkeypatch.setenv("AI_INTERVIEWER_REVIEWER_AUTH_KEY", "")
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "audit.sqlite3")
    api_main.PERSISTENCE.ensure_schema()
    monkeypatch.setattr(studio_graph.time, "sleep", lambda _: None)

    class Adapter:
        calls = 0

        def assess_turn(self, *, answer, competency, role, doc_type, grounded_sources):
            self.calls += 1
            if self.calls >= 3:
                raise LlmAdapterError("test provider failure")
            return LlmTurnAssessment(
                score=0.8,
                off_topic=False,
                mixed_signal=False,
                evidence=[answer],
                provider="test-provider",
                model=f"model-{self.calls}",
            )

    adapter = Adapter()
    monkeypatch.setattr(studio_graph, "build_llm_adapter_from_environment", lambda: adapter)
    client = TestClient(api_main.app)
    try:
        started = client.post(
            "/run/start", json={"role": "backend_engineer", "doc_type": "role_description"}
        )
        assert started.status_code == 200
        run_id = started.json()["run_id"]
        warmup = client.post("/run/answer", json={"run_id": run_id, "answer": "Warm up"})
        assert warmup.status_code == 200
        assert warmup.json()["graph_state"]["llm_trace"] is None

        answer = "I debug production incidents with traces and root cause analysis."
        first = client.post("/run/answer", json={"run_id": run_id, "answer": answer})
        assert first.status_code == 200
        assert first.json()["completed"] is False
        expected_first = {
            "provider": "test-provider",
            "model": "model-1",
            "fallback_used": False,
            "engine": "studio",
        }
        assert first.json()["graph_state"]["llm_trace"] == expected_first

        second = client.post("/run/answer", json={"run_id": run_id, "answer": answer})
        assert second.status_code == 200
        assert second.json()["completed"] is False
        expected_second = {**expected_first, "model": "model-2"}
        assert second.json()["graph_state"]["llm_trace"] == expected_second

        third = client.post("/run/answer", json={"run_id": run_id, "answer": answer})
        assert third.status_code == 200
        assert third.json()["completed"] is True
        expected_fallback = {
            "provider": "deterministic",
            "model": "local-evaluator",
            "fallback_used": True,
            "engine": "studio",
        }
        assert third.json()["graph_state"]["llm_trace"] == expected_fallback

        audit = client.get(f"/runs/{run_id}/audit")
        assert audit.status_code == 200
        payload = audit.json()
        completed_events = [
            event for event in payload["events"]
            if event["event_type"] in {"turn_completed", "run_completed"}
        ]
        assert [event["payload"]["graph_state"]["llm_trace"] for event in completed_events] == [
            expected_first,
            expected_second,
            expected_fallback,
        ]
        checkpoints = {
            checkpoint["state"]["evaluated_turns"]: checkpoint["state"]["llm_trace"]
            for checkpoint in payload["checkpoints"]
        }
        assert checkpoints[0] is None
        assert checkpoints[1] == expected_first
        assert checkpoints[2] == expected_second
        assert checkpoints[3] == expected_fallback
    finally:
        api_main.RUN_STATE.clear()
        close_checkpointed_graph()


def test_run_restores_from_sqlite_and_exposes_audit_bundle(tmp_path: Path) -> None:
    api_main.RUN_STATE.clear()
    api_main.PERSISTENCE._db_path = tmp_path / "ai_interviewer.sqlite3"  # type: ignore[attr-defined]
    api_main.PERSISTENCE.ensure_schema()

    client = TestClient(api_main.app)

    start_response = client.post(
        "/run/start", json={"role": "backend_engineer", "doc_type": "role_description"}
    )
    assert start_response.status_code == 200
    start_payload = start_response.json()
    run_id = start_payload["run_id"]
    asked_question = start_payload["question"]

    api_main.RUN_STATE.clear()

    warmup_response = client.post(
        "/run/answer",
        json={"run_id": run_id, "answer": "I recently improved a service reliability problem."},
    )
    assert warmup_response.status_code == 200
    asked_question = warmup_response.json()["question"]

    answer_response = client.post(
        "/run/answer",
        json={
            "run_id": run_id,
            "answer": "I isolate the failing layer, reproduce it, and check the traces.",
        },
    )
    assert answer_response.status_code == 200
    answer_payload = answer_response.json()

    assert answer_payload["run_id"] == run_id
    assert answer_payload["review_state"]["decision_trail_count"] >= 1
    assert answer_payload["graph_state"]["decision_log_tail"]

    audit_response = client.get(f"/runs/{run_id}/audit")
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()
    first_turn_event = next(
        item["payload"] for item in audit_payload["events"] if item["event_type"] == "turn_completed"
    )
    assert first_turn_event["answer"] == "I isolate the failing layer, reproduce it, and check the traces."
    assert first_turn_event["question"] == asked_question

    answers_sent = 1
    while not answer_payload["completed"] and answers_sent < answer_payload["total_questions"]:
        asked_question = answer_payload["question"]
        answer_response = client.post(
            "/run/answer",
            json={"run_id": run_id, "answer": "I am not sure."},
        )
        assert answer_response.status_code == 200
        answer_payload = answer_response.json()
        answers_sent += 1

        audit_response = client.get(f"/runs/{run_id}/audit")
        audit_payload = audit_response.json()
        latest_event = audit_payload["events"][-1]
        assert latest_event["payload"]["question"] == asked_question

    assert answer_payload["completed"] is True
    assert audit_payload["events"][-1]["event_type"] == "run_completed"

    assert audit_payload["run"]["run_id"] == run_id
    assert audit_payload["run"]["status"] == "in_review"
    assert len(audit_payload["events"]) >= 2
    assert len(audit_payload["checkpoints"]) >= 2
    assert audit_payload["events"][0]["event_type"] == "run_started"
    assert audit_payload["checkpoints"][0]["checkpoint_index"] == 0

    with api_main.PERSISTENCE._connect() as connection:  # type: ignore[attr-defined]
        turn_record = connection.execute(
            "SELECT question,answer,grounded_context_json FROM turn_records WHERE run_id=? AND answer=?",
            (run_id, "I isolate the failing layer, reproduce it, and check the traces."),
        ).fetchone()
    assert turn_record is not None
    assert turn_record["answer"] == "I isolate the failing layer, reproduce it, and check the traces."