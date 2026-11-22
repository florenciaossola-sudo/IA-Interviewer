from __future__ import annotations

import html
import logging
import os
from datetime import datetime
from typing import Protocol

import resend

from services.api.interviews import InterviewRecord

logger = logging.getLogger(__name__)


class NotificationError(RuntimeError):
    pass


class Notifier(Protocol):
    status: str

    def send_invitation(
        self,
        *,
        interview: InterviewRecord,
        candidate_url: str,
        idempotency_key: str,
    ) -> None: ...


def _format_datetime(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime(
        "%B %d, %Y at %I:%M %p %Z"
    )


def _invitation_content(interview: InterviewRecord, candidate_url: str) -> tuple[str, str, str]:
    role = interview.role_id.replace("_", " ").title()
    scheduled = _format_datetime(interview.scheduled_at)
    expires = _format_datetime(interview.expires_at)
    subject = f"Your {role} interview invitation"
    text = (
        f"Hello {interview.candidate_name},\n\n"
        f"You are invited to interview for {role}.\n"
        f"Scheduled: {scheduled}\n"
        f"Link expires: {expires}\n\n"
        f"Start your interview: {candidate_url}\n"
    )
    safe_name = html.escape(interview.candidate_name)
    safe_role = html.escape(role)
    safe_scheduled = html.escape(scheduled)
    safe_expires = html.escape(expires)
    safe_url = html.escape(candidate_url, quote=True)
    body = (
        "<!doctype html><html><body "
        'style="font-family:Arial,sans-serif;color:#172033;line-height:1.5">'
        f"<p>Hello {safe_name},</p>"
        f"<p>You are invited to interview for <strong>{safe_role}</strong>.</p>"
        f"<p><strong>Scheduled:</strong> {safe_scheduled}<br>"
        f"<strong>Link expires:</strong> {safe_expires}</p>"
        f"<p><a href=\"{safe_url}\">Open your interview</a></p></body></html>"
    )
    return subject, text, body


class LogNotifier:
    status = "logged"

    def send_invitation(
        self,
        *,
        interview: InterviewRecord,
        candidate_url: str,
        idempotency_key: str,
    ) -> None:
        _ = candidate_url, idempotency_key
        logger.info(
            "Email stub recorded candidate invitation: interview_id=%s recipient=%s",
            interview.interview_id,
            interview.candidate_email,
        )


class ResendNotifier:
    status = "sent"

    def __init__(self, api_key: str, from_address: str) -> None:
        resend.api_key = api_key
        self._from_address = from_address

    def send_invitation(
        self,
        *,
        interview: InterviewRecord,
        candidate_url: str,
        idempotency_key: str,
    ) -> None:
        subject, text, body = _invitation_content(interview, candidate_url)
        resend.Emails.send(
            {
                "from": self._from_address,
                "to": [interview.candidate_email],
                "subject": subject,
                "text": text,
                "html": body,
            },
            options={"idempotency_key": idempotency_key},
        )


def build_notifier() -> Notifier:
    backend = os.getenv("AI_INTERVIEWER_EMAIL_BACKEND", "log").strip().lower()
    if backend == "log":
        return LogNotifier()
    if backend != "resend":
        raise NotificationError(f"Unsupported email backend: {backend}")

    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_address = os.getenv("AI_INTERVIEWER_EMAIL_FROM", "").strip()
    if not api_key:
        raise NotificationError(
            "RESEND_API_KEY is required when AI_INTERVIEWER_EMAIL_BACKEND=resend."
        )
    if not from_address:
        raise NotificationError("AI_INTERVIEWER_EMAIL_FROM is required when Resend is enabled.")
    return ResendNotifier(api_key=api_key, from_address=from_address)


def send_invitation(
    *,
    notifier: Notifier,
    interview: InterviewRecord,
    candidate_url: str,
    attempt: int,
) -> str:
    notifier.send_invitation(
        interview=interview,
        candidate_url=candidate_url,
        idempotency_key=f"candidate-invitation-{interview.interview_id}-{attempt}",
    )
    return notifier.status