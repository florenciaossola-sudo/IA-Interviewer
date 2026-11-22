from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.api import notifications as api_notifications
from services.api.interviews import InterviewRepository


def test_resend_notifier_uses_sdk_with_idempotency_key(
    tmp_path: Path, monkeypatch
) -> None:
    repository = InterviewRepository(tmp_path / "interviews.sqlite3")
    now = datetime.now(timezone.utc)
    interview, _ = repository.create(
        candidate_name="Ada Lovelace",
        candidate_email="ada@example.test",
        role_id="backend_engineer",
        job_offer="Build reliable APIs",
        scheduled_at=(now + timedelta(hours=1)).isoformat(),
        expires_at=(now + timedelta(days=1)).isoformat(),
    )
    captured: dict[str, Any] = {}

    def fake_send(params: dict[str, Any], options: dict[str, str] | None = None) -> None:
        captured["params"] = params
        captured["options"] = options

    monkeypatch.setattr(api_notifications.resend, "api_key", "re_test_key")
    monkeypatch.setattr(
        api_notifications.resend.Emails,
        "send",
        staticmethod(fake_send),
    )
    notifier = api_notifications.ResendNotifier(
        api_key="re_test_key",
        from_address="AI Interviewer <onboarding@resend.dev>",
    )

    notifier.send_invitation(
        interview=interview,
        candidate_url="https://interviews.example.test/?interview=test-token",
        idempotency_key="invitation-attempt-1",
    )

    params = captured["params"]
    assert api_notifications.resend.api_key == "re_test_key"
    assert params["from"] == "AI Interviewer <onboarding@resend.dev>"
    assert params["to"] == ["ada@example.test"]
    assert params["subject"] == "Your Backend Engineer interview invitation"
    assert "https://interviews.example.test/?interview=test-token" in params["html"]
    assert captured["options"] == {"idempotency_key": "invitation-attempt-1"}