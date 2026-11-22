from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.main import app


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_role_question_limit_is_saved_and_used_for_interviews() -> None:
    client = TestClient(app)
    role_id = f"question_limit_{uuid4().hex}"

    invalid_response = client.put(
        f"/admin/roles/{role_id}/configuration", json={"max_turns": 11}
    )
    assert invalid_response.status_code == 422

    config_response = client.put(
        f"/admin/roles/{role_id}/configuration", json={"max_turns": 5}
    )
    assert config_response.status_code == 200
    assert config_response.json()["max_turns"] == 5

    start_response = client.post(
        "/run/start", json={"role": role_id, "doc_type": "role_description"}
    )
    assert start_response.status_code == 200
    assert start_response.json()["total_questions"] == 5
    assert start_response.json()["graph_state"]["max_turns"] == 5


def test_run_flow_completes_in_three_answers() -> None:
    client = TestClient(app)

    start_response = client.post(
        "/run/start", json={"role": "backend_engineer", "doc_type": "role_description"}
    )
    assert start_response.status_code == 200
    start_payload = start_response.json()

    run_id = start_payload["run_id"]
    assert start_payload["role"] == "backend_engineer"
    assert start_payload["doc_type"] == "role_description"
    assert start_payload["question_index"] == 0
    assert start_payload["warmup"] is True
    assert start_payload["completed"] is False
    assert isinstance(start_payload["grounded_context"], list)
    assert isinstance(start_payload["citation_list"], list)
    assert start_payload["review_state"]["active_competency"] == "debugging"
    assert start_payload["review_state"]["turn_index"] == 0
    assert start_payload["review_state"]["completed"] is False
    assert start_payload["review_state"]["decision_trail_count"] == 0
    assert start_payload["review_state"]["competency_coverage"] == 0.3333
    assert start_payload["review_state"]["competency_coverage_target"] == 1.0
    assert start_payload["review_state"]["competency_coverage_met"] is False
    assert start_payload["review_state"]["cumulative_confidence"] == 0.0
    assert start_payload["review_state"]["cumulative_confidence_target"] == 0.7
    assert start_payload["review_state"]["cumulative_confidence_met"] is False
    assert start_payload["review_state"]["safety_turn_limit"] == 3
    assert start_payload["review_state"]["safety_turn_limit_reached"] is False
    assert start_payload["review_state"]["off_topic_count"] == 0
    assert start_payload["graph_state"]["current_competency"] == "debugging"
    assert start_payload["graph_state"]["current_turn_index"] == 0
    assert start_payload["graph_state"]["max_turns"] == 3
    assert start_payload["graph_state"]["total_competencies"] == 3
    assert start_payload["graph_state"]["remaining_competencies"] == 2
    assert start_payload["graph_state"]["evaluated_turns"] == 0
    assert start_payload["graph_state"]["confidence_sum"] == 0.0
    assert start_payload["graph_state"]["confidence_average"] == 0.0
    assert start_payload["graph_state"]["off_topic_count"] == 0
    assert start_payload["graph_state"]["final_route"] is None
    assert start_payload["graph_state"]["decision_summary"].startswith("competency=debugging")
    assert start_payload["graph_state"]["route_history"] == []
    assert isinstance(start_payload["graph_state"]["decision_log_tail"], list)
    assert start_payload["graph_state"]["llm_trace"] is None
    if start_payload["grounded_context"]:
        assert all(item["role"] == "backend_engineer" for item in start_payload["grounded_context"])
        assert all(
            item["doc_type"] == "role_description" for item in start_payload["grounded_context"]
        )
    if start_payload["citation_list"]:
        assert all(item["source_id"] for item in start_payload["citation_list"])
        assert all(item["role"] == "backend_engineer" for item in start_payload["citation_list"])

    warmup_response = client.post(
        "/run/answer",
        json={"run_id": run_id, "answer": "I recently improved a service reliability problem."},
    )
    assert warmup_response.status_code == 200
    assert warmup_response.json()["warmup"] is False
    assert warmup_response.json()["question_index"] == 1

    answers = [
        "I debug production incidents with root cause analysis.",
        "I use API versioning and backward-compatible deprecation.",
        "I reduce flaky tests and keep CI deterministic.",
    ]

    for index, answer in enumerate(answers, start=1):
        response = client.post(
            "/run/answer",
            json={
                "run_id": run_id,
                "answer": answer,
                "role": "backend_engineer",
                "doc_type": "role_description",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        if index < 3:
            assert payload["completed"] is False
            assert payload["question"] is not None

    final_payload = payload
    assert final_payload["completed"] is True
    assert final_payload["question"] is None
    assert final_payload["role"] == "backend_engineer"
    assert final_payload["doc_type"] == "role_description"
    assert "citation_list" in final_payload
    assert final_payload["review_state"]["completed"] is True
    assert final_payload["review_state"]["competency_coverage"] == 1.0
    assert final_payload["review_state"]["competency_coverage_met"] is True
    assert isinstance(final_payload["review_state"]["cumulative_confidence"], float)
    assert final_payload["review_state"]["route_history"]
    assert final_payload["graph_state"]["final_route"] in {"conclude", "escalate"}
    assert final_payload["graph_state"]["evaluated_turns"] == 3
    assert isinstance(final_payload["graph_state"]["confidence_average"], float)
    assert final_payload["graph_state"]["route_history"]
    assert isinstance(final_payload["graph_state"]["decision_summary"], str)
    assert isinstance(final_payload["graph_state"]["llm_trace"], dict)
    assert final_payload["graph_state"]["llm_trace"]["provider"] == "deterministic"


def test_rejects_empty_answer() -> None:
    client = TestClient(app)
    start_response = client.post(
        "/run/start", json={"role": "backend_engineer", "doc_type": "role_description"}
    )

    run_id = start_response.json()["run_id"]
    response = client.post("/run/answer", json={"run_id": run_id, "answer": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Answer cannot be empty"


def test_run_answer_can_override_retrieval_filters() -> None:
    client = TestClient(app)
    start_response = client.post(
        "/run/start", json={"role": "backend_engineer", "doc_type": "role_description"}
    )
    run_id = start_response.json()["run_id"]

    warmup_response = client.post(
        "/run/answer",
        json={"run_id": run_id, "answer": "I recently improved a service reliability problem."},
    )
    assert warmup_response.status_code == 200

    response = client.post(
        "/run/answer",
        json={
            "run_id": run_id,
            "answer": "How do we reduce flaky tests in CI?",
            "role": "backend_engineer",
            "doc_type": "engineering_standard",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == "backend_engineer"
    assert payload["doc_type"] == "engineering_standard"
    assert payload["grounded_context"]
    assert payload["citation_list"]
    assert payload["review_state"]["active_competency"] in {
        "debugging",
        "api_design",
        "test_reliability",
    }
    assert payload["graph_state"]["current_competency"] in {
        "debugging",
        "api_design",
        "test_reliability",
    }
    assert payload["review_state"]["competency_coverage"] >= 0.3333
    assert isinstance(payload["review_state"]["cumulative_confidence"], float)
    assert payload["graph_state"]["max_turns"] == 3
    assert isinstance(payload["graph_state"]["decision_summary"], str)
    assert isinstance(payload["graph_state"]["route_history"], list)
    assert all(item["doc_type"] == "engineering_standard" for item in payload["grounded_context"])
    assert all(item["doc_type"] == "engineering_standard" for item in payload["citation_list"])
