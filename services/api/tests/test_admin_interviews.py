from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from services.agent.graph.llm import LlmTurnAssessment
from services.api import main as api_main
from services.api.interviews import InterviewRepository, _PostgresConnection


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def test_postgres_interview_adapter_translates_sqlite_specific_syntax() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.statements: list[tuple[str, object]] = []

        def execute(self, statement: str, parameters: object = ()):
            self.statements.append((statement, parameters))
            return None

    connection = FakeConnection()
    adapter = _PostgresConnection(connection)

    adapter.execute("CREATE TABLE audit (event_id INTEGER PRIMARY KEY AUTOINCREMENT)")
    adapter.execute("SELECT * FROM interviews WHERE interview_id=?", ("ivw_test",))
    adapter.execute("BEGIN IMMEDIATE")

    assert connection.statements == [
        ("CREATE TABLE audit (event_id BIGSERIAL PRIMARY KEY)", ()),
        ("SELECT * FROM interviews WHERE interview_id=%s", ("ivw_test",)),
        ("BEGIN", ()),
    ]


def test_admin_scheduled_interview_link_lifecycle_and_start_gate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api_main, "INTERVIEW_REPOSITORY", InterviewRepository(tmp_path / "interviews.sqlite3"))
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "runs.sqlite3")
    api_main.PERSISTENCE.ensure_schema()
    client = TestClient(api_main.app)
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    expires = start + timedelta(days=1)

    created = client.post(
        "/admin/interviews",
        json={
            "candidate_name": "Ada Lovelace",
            "candidate_email": "ada@example.test",
            "role_id": "backend_engineer",
            "job_offer": "Build reliable APIs",
            "scheduled_at": _iso(start),
            "expires_at": _iso(expires),
        },
    )
    assert created.status_code == 200, created.text
    interview_id = created.json()["interview"]["interview_id"]
    old_link = created.json()["candidate_url"]
    old_token = old_link.split("interview=", 1)[1]

    listing = client.get("/admin/interviews", params={"search": "ada@", "status": "scheduled", "limit": 1})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["interview_id"] == interview_id

    exported = client.get("/admin/interviews/export.csv")
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert interview_id in exported.text

    not_yet_active = client.post("/run/start", json={"interview_token": old_token})
    assert not_yet_active.status_code == 410

    public_info = client.get(f"/candidate/interviews/{old_token}")
    assert public_info.status_code == 200
    assert public_info.json()["candidate_name"] == "Ada Lovelace"
    assert public_info.json()["status"] == "scheduled"

    activated = client.post(f"/admin/interviews/{interview_id}/activate")
    assert activated.status_code == 200
    started = client.post("/run/start", json={"interview_token": old_token})
    assert started.status_code == 200, started.text
    assert started.json()["role"] == "backend_engineer"


def test_candidate_link_resumes_persisted_run_after_memory_loss(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        api_main, "INTERVIEW_REPOSITORY", InterviewRepository(tmp_path / "interviews.sqlite3")
    )
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "runs.sqlite3")
    monkeypatch.setenv("AI_INTERVIEWER_QUESTION_LLM_ENABLED", "0")
    monkeypatch.setenv("AI_INTERVIEWER_LLM_ENABLED", "0")
    api_main.PERSISTENCE.ensure_schema()
    api_main.RUN_STATE.clear()
    client = TestClient(api_main.app)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/admin/interviews",
        json={
            "candidate_name": "Ada Lovelace",
            "candidate_email": "ada@example.test",
            "role_id": "backend_engineer",
            "scheduled_at": _iso(now - timedelta(minutes=1)),
            "expires_at": _iso(now + timedelta(days=1)),
        },
    )
    token = created.json()["candidate_url"].split("interview=", 1)[1]

    integrity = {
        "disclosure_accepted": True,
        "focus_telemetry_enabled": False,
        "suppressed_signal_families": ["focus", "motion"],
    }
    initial = client.post(
        "/run/start", json={"interview_token": token, "integrity": integrity}
    )
    run_id = initial.json()["run_id"]
    warmup = client.post(
        "/run/answer",
        json={
            "run_id": run_id,
            "answer": "I improved the reliability of a service.",
            "integrity": integrity,
        },
    )
    saved_question = warmup.json()["question"]
    public_info = client.get(f"/candidate/interviews/{token}")
    assert public_info.json()["integrity_preferences"] == integrity
    api_main.RUN_STATE.clear()

    resumed = client.post("/run/start", json={"interview_token": token})

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["run_id"] == run_id
    assert resumed.json()["question"] == saved_question
    assert resumed.json()["question_index"] == 1
    assert resumed.json()["warmup"] is False

    answered = client.post(
        "/run/answer",
        json={"run_id": run_id, "answer": "I isolate failures with traces and reproducible tests."},
    )
    next_question = answered.json()["question"]
    api_main.RUN_STATE.clear()

    resumed_again = client.post("/run/start", json={"interview_token": token})

    assert resumed_again.status_code == 200, resumed_again.text
    assert resumed_again.json()["run_id"] == run_id
    assert resumed_again.json()["question"] == next_question
    assert resumed_again.json()["question_index"] == 2


def test_retries_answer_when_evaluation_checkpoint_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        api_main, "INTERVIEW_REPOSITORY", InterviewRepository(tmp_path / "interviews.sqlite3")
    )
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "runs.sqlite3")
    monkeypatch.setenv("AI_INTERVIEWER_QUESTION_LLM_ENABLED", "0")
    monkeypatch.setenv("AI_INTERVIEWER_LLM_ENABLED", "0")
    api_main.PERSISTENCE.ensure_schema()
    api_main.RUN_STATE.clear()

    from services.agent.graph import studio_graph

    class TransientAdapter:
        calls = 0

        def assess_turn(self, **kwargs):
            _ = kwargs
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated timeout before timeout handling was deployed")
            return LlmTurnAssessment(
                score=0.65,
                off_topic=False,
                mixed_signal=False,
                evidence=["identified the cause and checked logs"],
                provider="test",
                model="stub",
            )

    adapter = TransientAdapter()
    monkeypatch.setattr(studio_graph, "build_llm_adapter_from_environment", lambda: adapter)
    client = TestClient(api_main.app, raise_server_exceptions=False)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/admin/interviews",
        json={
            "candidate_name": "Ada Lovelace",
            "candidate_email": "ada@example.test",
            "role_id": "backend_engineer",
            "scheduled_at": _iso(now - timedelta(minutes=1)),
            "expires_at": _iso(now + timedelta(days=1)),
        },
    )
    token = created.json()["candidate_url"].split("interview=", 1)[1]
    run_id = client.post("/run/start", json={"interview_token": token}).json()["run_id"]
    client.post(
        "/run/answer",
        json={"run_id": run_id, "answer": "I improved service reliability."},
    )
    answer = "I identified the cause and checked logs to resolve the production issue."

    failed = client.post("/run/answer", json={"run_id": run_id, "answer": answer})
    assert failed.status_code == 500

    retried = client.post("/run/answer", json={"run_id": run_id, "answer": answer})

    assert retried.status_code == 200, retried.text
    assert retried.json()["graph_state"]["evaluated_turns"] == 1
    assert adapter.calls == 2


def test_regenerate_and_revoke_invalidate_candidate_links(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api_main, "INTERVIEW_REPOSITORY", InterviewRepository(tmp_path / "interviews.sqlite3"))
    client = TestClient(api_main.app)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/admin/interviews",
        json={
            "candidate_name": "Grace Hopper",
            "candidate_email": "grace@example.test",
            "role_id": "frontend_engineer",
            "scheduled_at": _iso(now - timedelta(minutes=1)),
            "expires_at": _iso(now + timedelta(days=1)),
        },
    )
    assert created.status_code == 200
    interview_id = created.json()["interview"]["interview_id"]
    old_token = created.json()["candidate_url"].split("interview=", 1)[1]

    regenerated = client.post(f"/admin/interviews/{interview_id}/regenerate-link")
    new_token = regenerated.json()["candidate_url"].split("interview=", 1)[1]
    assert new_token != old_token
    assert client.get(f"/candidate/interviews/{old_token}").status_code == 404
    assert client.get(f"/candidate/interviews/{new_token}").status_code == 200

    assigned = client.patch(
        f"/admin/interviews/{interview_id}/reviewer",
        json={"reviewer": "reviewer@example.test"},
    )
    assert assigned.json()["reviewer"] == "reviewer@example.test"

    revoked = client.post(f"/admin/interviews/{interview_id}/revoke")
    assert revoked.status_code == 200
    assert client.get(f"/candidate/interviews/{new_token}").status_code == 410


def test_candidate_interview_keeps_empty_job_offer_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        api_main, "INTERVIEW_REPOSITORY", InterviewRepository(tmp_path / "interviews.sqlite3")
    )
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "roles.sqlite3")
    api_main.PERSISTENCE.ensure_schema()
    api_main.PERSISTENCE.save_role(
        role_id="backend_engineer",
        title="Backend Engineer",
        location="Remote",
        description="This role description must not become interview context.",
    )
    client = TestClient(api_main.app)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/admin/interviews",
        json={
            "candidate_name": "Katherine Johnson",
            "candidate_email": "katherine@example.test",
            "role_id": "backend_engineer",
            "job_offer": "",
            "scheduled_at": _iso(now - timedelta(minutes=1)),
            "expires_at": _iso(now + timedelta(days=1)),
        },
    )
    assert created.status_code == 200
    token = created.json()["candidate_url"].split("interview=", 1)[1]

    public_info = client.get(f"/candidate/interviews/{token}")

    assert public_info.status_code == 200
    assert public_info.json()["role_description"] == (
        "This role description must not become interview context."
    )
    assert public_info.json()["job_offer"] == ""


def test_activation_sends_invitation_once_and_records_delivery(tmp_path: Path, monkeypatch) -> None:
    repository = InterviewRepository(tmp_path / "interviews.sqlite3")
    monkeypatch.setattr(api_main, "INTERVIEW_REPOSITORY", repository)
    client = TestClient(api_main.app)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/admin/interviews",
        json={
            "candidate_name": "Ada Lovelace",
            "candidate_email": "ada@example.test",
            "role_id": "backend_engineer",
            "job_offer": "Build reliable APIs",
            "scheduled_at": _iso(now + timedelta(hours=1)),
            "expires_at": _iso(now + timedelta(days=1)),
        },
    )
    interview_id = created.json()["interview"]["interview_id"]
    initial_token = created.json()["candidate_url"].split("interview=", 1)[1]

    class FakeNotifier:
        status = "sent"

        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def send_invitation(self, *, interview, candidate_url, idempotency_key) -> None:
            _ = idempotency_key
            self.calls.append((interview.candidate_email, candidate_url))

    notifier = FakeNotifier()
    monkeypatch.setattr(api_main, "build_notifier", lambda: notifier)

    activated = client.post(f"/admin/interviews/{interview_id}/activate")

    assert activated.status_code == 200
    assert activated.json()["invitation_status"] == "sent"
    assert activated.json()["invitation_attempts"] == 1
    assert notifier.calls == [
        ("ada@example.test", f"http://127.0.0.1:4174/?interview={initial_token}")
    ]
    assert client.post(f"/admin/interviews/{interview_id}/send-invitation").status_code == 409
    assert len(notifier.calls) == 1
    audit = client.get("/admin/audit-events", params={"event_type": "interview.invitation.sent"})
    assert audit.json()["total"] == 1


def test_failed_invitation_can_be_retried_from_admin(tmp_path: Path, monkeypatch) -> None:
    repository = InterviewRepository(tmp_path / "interviews.sqlite3")
    monkeypatch.setattr(api_main, "INTERVIEW_REPOSITORY", repository)
    client = TestClient(api_main.app)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/admin/interviews",
        json={
            "candidate_name": "Grace Hopper",
            "candidate_email": "grace@example.test",
            "role_id": "backend_engineer",
            "job_offer": "Build reliable APIs",
            "scheduled_at": _iso(now + timedelta(hours=1)),
            "expires_at": _iso(now + timedelta(days=1)),
        },
    )
    interview_id = created.json()["interview"]["interview_id"]

    class FlakyNotifier:
        status = "sent"

        def __init__(self) -> None:
            self.calls = 0

        def send_invitation(self, *, interview, candidate_url, idempotency_key) -> None:
            _ = interview, candidate_url, idempotency_key
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Resend temporarily unavailable")

    notifier = FlakyNotifier()
    monkeypatch.setattr(api_main, "build_notifier", lambda: notifier)

    activated = client.post(f"/admin/interviews/{interview_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["invitation_status"] == "failed"
    assert activated.json()["invitation_error"] == "Resend temporarily unavailable"

    retried = client.post(f"/admin/interviews/{interview_id}/send-invitation")

    assert retried.status_code == 200
    assert retried.json()["invitation_status"] == "sent"
    assert retried.json()["invitation_attempts"] == 2
    assert notifier.calls == 2


def test_logged_invitation_can_be_sent_after_resend_is_configured(
    tmp_path: Path, monkeypatch
) -> None:
    repository = InterviewRepository(tmp_path / "interviews.sqlite3")
    monkeypatch.setattr(api_main, "INTERVIEW_REPOSITORY", repository)
    client = TestClient(api_main.app)
    now = datetime.now(timezone.utc)
    created = client.post(
        "/admin/interviews",
        json={
            "candidate_name": "Ada Lovelace",
            "candidate_email": "ada@example.test",
            "role_id": "backend_engineer",
            "job_offer": "Build reliable APIs",
            "scheduled_at": _iso(now + timedelta(hours=1)),
            "expires_at": _iso(now + timedelta(days=1)),
        },
    )
    interview_id = created.json()["interview"]["interview_id"]
    activated = client.post(f"/admin/interviews/{interview_id}/activate")
    assert activated.json()["invitation_status"] == "logged"

    class FakeResendNotifier:
        status = "sent"

        def send_invitation(self, *, interview, candidate_url, idempotency_key) -> None:
            _ = interview, candidate_url, idempotency_key

    monkeypatch.setattr(api_main, "build_notifier", FakeResendNotifier)

    resent = client.post(f"/admin/interviews/{interview_id}/send-invitation")

    assert resent.status_code == 200
    assert resent.json()["invitation_status"] == "sent"
    assert resent.json()["invitation_attempts"] == 2


def test_bulk_import_rejects_invalid_schedule_without_creating_rows(tmp_path: Path, monkeypatch) -> None:
    repository = InterviewRepository(tmp_path / "interviews.sqlite3")
    monkeypatch.setattr(api_main, "INTERVIEW_REPOSITORY", repository)
    client = TestClient(api_main.app)

    response = client.post(
        "/admin/interviews/bulk",
        content=(
            "candidate_name,candidate_email,role_id,scheduled_at,expires_at\n"
            "Lin,lin@example.test,backend_engineer,not-a-date,also-not-a-date\n"
        ),
        headers={"Content-Type": "text/csv"},
    )
    assert response.status_code == 400
    assert repository.list()[1] == 0


def test_reviewer_integrity_disposition_requires_rationale_and_is_audited(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        api_main, "INTERVIEW_REPOSITORY", InterviewRepository(tmp_path / "interviews.sqlite3")
    )
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "runs.sqlite3")
    api_main.PERSISTENCE.ensure_schema()
    api_main.RUN_STATE.clear()
    client = TestClient(api_main.app)
    run = client.post("/run/start", json={"role": "backend_engineer"}).json()

    invalid = client.put(
        f"/runs/{run['run_id']}/integrity-disposition",
        json={"reviewer": "reviewer@example.test", "disposition": "confirmed", "rationale": "  "},
    )
    assert invalid.status_code == 400

    saved = client.put(
        f"/runs/{run['run_id']}/integrity-disposition",
        json={
            "reviewer": "reviewer@example.test",
            "disposition": "dismissed",
            "rationale": "Signals have a documented accommodation explanation.",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["disposition"] == "dismissed"

    loaded = client.get(f"/runs/{run['run_id']}/integrity-disposition")
    assert loaded.status_code == 200
    assert loaded.json()["reviewer"] == "reviewer@example.test"

    audit = client.get("/admin/audit-events", params={"event_type": "review.integrity_disposition"})
    assert audit.status_code == 200
    assert audit.json()["total"] == 1


def test_reviewer_follow_up_assignment_and_recommendation_letter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        api_main, "INTERVIEW_REPOSITORY", InterviewRepository(tmp_path / "interviews.sqlite3")
    )
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "runs.sqlite3")
    api_main.PERSISTENCE.ensure_schema()
    api_main.PERSISTENCE.save_run_start(
        run_id="iv_follow_up",
        role="backend_engineer",
        doc_type="role_description",
        state={"final_route": "conclude"},
        payload={"run_id": "iv_follow_up", "assigned_reviewer": "alex"},
    )
    api_main.PERSISTENCE.save_turn(
        run_id="iv_follow_up",
        role="backend_engineer",
        doc_type="role_description",
        state={"final_route": "conclude"},
        payload={
            "run_id": "iv_follow_up",
            "completed": True,
            "evaluation_score": 0.8,
            "graph_state": {"final_route": "conclude"},
        },
        checkpoint_index=1,
        completed=True,
    )
    client = TestClient(api_main.app)

    forbidden = client.post(
        "/runs/iv_follow_up/follow-up",
        json={"reviewer": "sam", "requested_action": "Clarify API ownership."},
    )
    assert forbidden.status_code == 403

    requested = client.post(
        "/runs/iv_follow_up/follow-up",
        json={"reviewer": "alex", "requested_action": "Clarify API ownership."},
    )
    assert requested.status_code == 200
    assert requested.json()["status"] == "requested"

    updated = client.patch(
        "/runs/iv_follow_up/follow-up",
        json={"reviewer": "alex", "status": "completed", "note": "Completed in a second call."},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"

    reviewed = client.post(
        "/runs/iv_follow_up/review",
        json={"reviewer_name": "alex", "decision": "approved", "rationale": "Evidence is sufficient."},
    )
    assert reviewed.status_code == 200

    letter = client.post("/runs/iv_follow_up/recommendation-letter?reviewer=alex")
    assert letter.status_code == 200
    assert "backend_engineer" in letter.json()["content"]
    assert "Evidence is sufficient." in letter.json()["content"]


def test_reviewer_authentication_protects_review_queue(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_INTERVIEWER_REVIEWER_AUTH_KEY", "local-reviewer-secret")
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "auth.sqlite3")
    api_main.PERSISTENCE.ensure_schema()
    client = TestClient(api_main.app)

    unauthorized = client.get("/review/queue")
    assert unauthorized.status_code == 401

    invalid = client.post(
        "/review/auth/login",
        json={"reviewer": "alex", "access_key": "wrong"},
    )
    assert invalid.status_code == 401

    login = client.post(
        "/review/auth/login",
        json={"reviewer": "alex", "access_key": "local-reviewer-secret"},
    )
    assert login.status_code == 200
    token = login.json()["token"]

    authorized = client.get("/review/queue", headers={"Authorization": f"Bearer {token}"})
    assert authorized.status_code == 200


def test_assessment_html_requires_finalized_review(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "assessment.sqlite3")
    api_main.PERSISTENCE.ensure_schema()
    api_main.PERSISTENCE.save_run_start(
        run_id="iv_assessment",
        role="backend_engineer",
        doc_type="role_description",
        state={"final_route": "conclude"},
        payload={"run_id": "iv_assessment"},
    )
    client = TestClient(api_main.app)

    pending = client.get("/runs/iv_assessment/assessment.html")
    assert pending.status_code == 409

    api_main.PERSISTENCE.save_turn(
        run_id="iv_assessment",
        role="backend_engineer",
        doc_type="role_description",
        state={"final_route": "conclude"},
        payload={"run_id": "iv_assessment", "completed": True, "answer": "A useful answer"},
        checkpoint_index=1,
        completed=True,
    )
    reviewed = client.post(
        "/runs/iv_assessment/review",
        json={"reviewer_name": "reviewer", "decision": "approved", "rationale": "Reviewed."},
    )
    assert reviewed.status_code == 200

    exported = client.get("/runs/iv_assessment/assessment.html")
    assert exported.status_code == 200
    assert "Interview Assessment" in exported.text
    assert "A useful answer" in exported.text


def test_answer_event_records_the_competency_that_was_scored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        api_main.PERSISTENCE, "_db_path", tmp_path / "runs.sqlite3"
    )
    api_main.PERSISTENCE.ensure_schema()
    api_main.RUN_STATE.clear()
    client = TestClient(api_main.app)

    started = client.post("/run/start", json={"role": "backend_engineer"})
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    warmup = client.post(
        "/run/answer",
        json={"run_id": run_id, "answer": "I recently improved a service reliability problem."},
    )
    assert warmup.status_code == 200
    answered = client.post(
        "/run/answer",
        json={"run_id": run_id, "answer": "I debug production incidents by tracing the root cause."},
    )
    assert answered.status_code == 200, answered.text

    events = api_main.PERSISTENCE.load_events(run_id)
    turn_event = next(event for event in events if event.event_type == "turn_completed")
    assert turn_event.payload["competency"] == "debugging"


def test_corpus_chunk_endpoint_returns_source_text(tmp_path: Path, monkeypatch) -> None:
    from services.agent.retrieval.service import GroundedRetrievalService

    fixture = Path(__file__).resolve().parents[2] / "agent" / "fixtures" / "corpus.json"
    retrieval_service = GroundedRetrievalService.from_fixture(fixture)
    monkeypatch.setattr(api_main, "RETRIEVAL_SERVICE", retrieval_service)
    client = TestClient(api_main.app)

    response = client.get("/admin/corpus/chunks/backend-role%3A%3Achunk-0")
    assert response.status_code == 200, response.text
    assert response.json()["chunk_id"] == "backend-role::chunk-0"
    assert response.json()["text"]


def test_review_override_requires_and_persists_replacement_outcome(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(api_main.PERSISTENCE, "_db_path", tmp_path / "runs.sqlite3")
    api_main.PERSISTENCE.ensure_schema()
    api_main.PERSISTENCE.save_run_start(
        run_id="iv_override",
        role="backend_engineer",
        doc_type="role_description",
        state={"role": "backend_engineer", "doc_type": "role_description"},
        payload={"run_id": "iv_override"},
    )
    api_main.PERSISTENCE.save_turn(
        run_id="iv_override",
        role="backend_engineer",
        doc_type="role_description",
        state={"role": "backend_engineer", "doc_type": "role_description"},
        payload={"run_id": "iv_override", "completed": True},
        checkpoint_index=1,
        completed=True,
    )
    client = TestClient(api_main.app)

    missing_target = client.post(
        "/runs/iv_override/review",
        json={"decision": "overridden", "rationale": "The system missed key evidence."},
    )
    assert missing_target.status_code == 400

    submitted = client.post(
        "/runs/iv_override/review",
        json={
            "reviewer_name": "reviewer@example.test",
            "decision": "overridden",
            "override_outcome": "conclude",
            "rationale": "The evidence supports completion.",
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["review"]["decision"] == "overridden"
    assert submitted.json()["review"]["override_outcome"] == "conclude"
    saved = api_main.PERSISTENCE.load_review_decision("iv_override")
    assert saved is not None
    assert saved.override_outcome == "conclude"
