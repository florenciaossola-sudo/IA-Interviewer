from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.api import main as api_main


def test_integrity_does_not_change_graph_state_bytes(tmp_path: Path) -> None:
    api_main.RUN_STATE.clear()
    api_main.PERSISTENCE._db_path = tmp_path / "ai_interviewer.sqlite3"  # type: ignore[attr-defined]
    api_main.PERSISTENCE.ensure_schema()

    client = TestClient(api_main.app)
    answers = [
        "I isolate the failing layer, reproduce it, and check the traces.",
        "I preserve backward compatibility by versioning carefully.",
        "I remove flaky tests and stabilize CI signals.",
    ]

    baseline = _run_interview(client, integrity_payload=None, answers=answers)
    integrity_enabled = _run_interview(
        client,
        integrity_payload={
            "disclosure_accepted": True,
            "focus_telemetry_enabled": True,
            "suppressed_signal_families": ["focus"],
            "telemetry_events": [
                {"signal_family": "focus", "event_type": "focus", "value": "answer-input"},
                {"signal_family": "timing", "event_type": "start_click", "value": "candidate"},
            ],
        },
        answers=answers,
    )

    assert json.dumps(baseline["graph_state"], sort_keys=True) == json.dumps(
        integrity_enabled["graph_state"], sort_keys=True
    )
    assert baseline["integrity_state"]["aai_index"] == 6
    assert any(
        evidence == "start_click: candidate"
        for signal in integrity_enabled["integrity_state"]["signal_breakdown"]
        for evidence in signal["evidence"]
    )
    assert integrity_enabled["integrity_state"]["baseline_available"] is True
    assert integrity_enabled["integrity_state"]["baseline_answer_length"] > 0
    assert isinstance(integrity_enabled["integrity_state"]["baseline_deviation_ratio"], float)


def test_telemetry_requires_disclosure_acceptance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "telemetry.sqlite3")
    api_main.PERSISTENCE.ensure_schema()
    api_main.RUN_STATE.clear()
    client = TestClient(api_main.app)

    response = client.post(
        "/run/start",
        json={
            "role": "backend_engineer",
            "integrity": {
                "disclosure_accepted": False,
                "telemetry_events": [
                    {"signal_family": "timing", "event_type": "click", "value": "candidate"}
                ],
            },
        },
    )

    assert response.status_code == 400
    assert "require an accepted integrity disclosure" in response.json()["detail"]


def _run_interview(
    client: TestClient,
    integrity_payload: dict | None,
    answers: list[str],
) -> dict[str, object]:
    start_payload: dict[str, object] = {"role": "backend_engineer", "doc_type": "role_description"}
    if integrity_payload is not None:
        start_payload["integrity"] = integrity_payload

    start_response = client.post("/run/start", json=start_payload)
    assert start_response.status_code == 200
    payload = start_response.json()
    run_id = payload["run_id"]

    for answer in answers:
        submit_payload: dict[str, object] = {"run_id": run_id, "answer": answer}
        if integrity_payload is not None:
            submit_payload["integrity"] = integrity_payload

        answer_response = client.post("/run/answer", json=submit_payload)
        assert answer_response.status_code == 200
        payload = answer_response.json()

    return payload