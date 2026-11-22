from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import hmac
import html
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from math import exp
from pathlib import Path
from statistics import median
from typing import Any, cast
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from services.agent.graph.checkpointing import close_checkpointed_graph, get_checkpointed_graph
from services.agent.graph.models import InterviewGraphState
from services.agent.graph.runtime import InterviewGraph, RuntimeStateRecord
from services.agent.graph.studio_graph import set_retrieval_service
from services.agent.integrity import (
    AccommodationDeclaration,
    IntegrityReport,
    SignalFamily,
    TelemetryEvent,
    analyze_integrity,
)
from services.agent.retrieval import GroundedRetrievalService
from services.agent.retrieval.types import CorpusDocument
from services.analytics.plane import (
    DEFAULT_POLICY_VERSION,
    DEFAULT_PROMPT_VERSION,
    compare_snapshot_ids,
    save_gold_snapshot,
    snapshot_to_dict,
)
from services.analytics.scheduler import run_drift_check_job, run_snapshot_sync_job
from services.api.corpus import MAX_DOCUMENT_BYTES, CorpusDocumentManager, CorpusDocumentRecord
from services.api.interviews import InterviewRecord, InterviewRepository
from services.api.notifications import build_notifier, send_invitation
from services.api.persistence import PERSISTENCE


@asynccontextmanager
async def lifespan(app: FastAPI):
    PERSISTENCE.ensure_schema()
    _index_saved_role_descriptions()
    activation_worker = asyncio.create_task(_scheduled_interview_activation_worker())
    try:
        yield
    finally:
        activation_worker.cancel()
        try:
            await activation_worker
        except asyncio.CancelledError:
            pass
        close_checkpointed_graph()


async def _scheduled_interview_activation_worker() -> None:
    while True:
        for interview_id, status in INTERVIEW_REPOSITORY.activate_due():
            INTERVIEW_REPOSITORY.record_audit(
                f"interview.auto_{status}", interview_id, {"source": "schedule_worker"}
            )
            if status == "active":
                _send_interview_invitation(interview_id, source="schedule_worker")
        stale_before = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        INTERVIEW_REPOSITORY.reset_stale_invitation_sends(stale_before)
        for interview in INTERVIEW_REPOSITORY.list_active_pending_invitations():
            _send_interview_invitation(interview.interview_id, source="schedule_worker")
        await asyncio.sleep(15)


def _send_interview_invitation(interview_id: str, *, source: str) -> InterviewRecord:
    record, claimed = INTERVIEW_REPOSITORY.claim_invitation_send(
        interview_id, allow_logged=source == "admin_retry"
    )
    if not claimed:
        return record

    try:
        token = INTERVIEW_REPOSITORY.get_candidate_token(interview_id)
        if token is None:
            _, token = INTERVIEW_REPOSITORY.regenerate_link(
                interview_id, reset_invitation_status=False
            )
            record = INTERVIEW_REPOSITORY.get(interview_id)
        candidate_base_url = os.getenv(
            "AI_INTERVIEWER_CANDIDATE_URL", "http://127.0.0.1:4174"
        ).rstrip("/")
        candidate_url = f"{candidate_base_url}/?interview={quote(token, safe='')}"
        notifier = build_notifier()
        delivery_status = send_invitation(
            notifier=notifier,
            interview=record,
            candidate_url=candidate_url,
            attempt=record.invitation_attempts,
        )
        updated = INTERVIEW_REPOSITORY.finish_invitation_send(interview_id, delivery_status)
    except Exception as exc:
        message = str(exc)[:500] or "Email delivery failed."
        updated = INTERVIEW_REPOSITORY.finish_invitation_send(
            interview_id, "failed", error=message
        )
        INTERVIEW_REPOSITORY.record_audit(
            "interview.invitation.failed",
            interview_id,
            {"source": source, "attempt": updated.invitation_attempts, "error": message},
        )
        return updated

    INTERVIEW_REPOSITORY.record_audit(
        f"interview.invitation.{delivery_status}",
        interview_id,
        {"source": source, "attempt": updated.invitation_attempts},
    )
    return updated


app = FastAPI(title="AI Interviewer API", version="0.1.0", lifespan=lifespan)


def _reviewer_auth_key() -> str:
    return os.getenv("AI_INTERVIEWER_REVIEWER_AUTH_KEY", "").strip()


def _issue_reviewer_token(reviewer: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"reviewer": reviewer, "v": 1}, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        _reviewer_auth_key().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}"


def _authenticated_reviewer(request: Request) -> str | None:
    auth_key = _reviewer_auth_key()
    if not auth_key:
        return None
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Reviewer authentication required")
    token = header.removeprefix("Bearer ")
    try:
        payload, signature = token.split(".", 1)
        expected = hmac.new(auth_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        reviewer = json.loads(decoded).get("reviewer", "").strip()
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid reviewer token") from None
    if not reviewer:
        raise HTTPException(status_code=401, detail="Invalid reviewer identity")
    return reviewer


# Configure basic logging for debugging provider requests
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.INFO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:4174",
        "http://localhost:4174",
        "http://127.0.0.1:4175",
        "http://localhost:4175",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartRunResponse(BaseModel):
    run_id: str
    role: str
    doc_type: str
    question: str
    question_index: int
    total_questions: int
    completed: bool
    grounded_context: list[GroundedContextItem]
    citation_list: list[CitationItem]
    review_state: ReviewStateItem
    graph_state: GraphStateItem
    integrity_state: IntegrityStateItem
    warmup: bool = False


class GroundedContextItem(BaseModel):
    chunk_id: str
    doc_id: str
    doc_type: str
    role: str
    text: str
    score: float


class CitationItem(BaseModel):
    source_id: str
    doc_id: str
    doc_type: str
    role: str


class DecisionLogItem(BaseModel):
    node: str
    route: str
    reason: str
    alternatives: list[str] = []


class GraphStateItem(BaseModel):
    current_competency: str
    current_turn_index: int
    max_turns: int
    total_competencies: int
    remaining_competencies: int
    evaluated_turns: int
    confidence_sum: float
    confidence_average: float
    off_topic_count: int
    final_route: str | None
    decision_summary: str
    route_history: list[str]
    decision_log_tail: list[DecisionLogItem]
    llm_trace: dict[str, Any] | None = None


class ReviewStateItem(BaseModel):
    active_competency: str
    turn_index: int
    completed: bool
    decision_summary: str
    route_history: list[str]
    decision_trail_count: int
    competency_coverage: float
    competency_coverage_target: float
    competency_coverage_met: bool
    cumulative_confidence: float
    cumulative_confidence_target: float
    cumulative_confidence_met: bool
    safety_turn_limit: int
    safety_turn_limit_reached: bool
    off_topic_count: int


class IntegrityTelemetryItem(BaseModel):
    signal_family: str
    event_type: str
    value: str


class IntegrityRequestItem(BaseModel):
    disclosure_accepted: bool = False
    focus_telemetry_enabled: bool = False
    suppressed_signal_families: list[str] = []
    telemetry_events: list[IntegrityTelemetryItem] = []
    current_metrics: dict[str, float] = Field(default_factory=dict)


class IntegrityBreakdownItem(BaseModel):
    signal_family: str
    event_count: int
    suppressed: bool
    evidence: list[str] = Field(default_factory=list)


class IntegrityStateItem(BaseModel):
    disclosure_accepted: bool
    focus_telemetry_enabled: bool
    aai_index: int
    signal_breakdown: list[IntegrityBreakdownItem]
    confounders: list[str]
    disposition: str
    suppressed_signal_families: list[str]
    baseline_available: bool = False
    baseline_answer_length: int | None = None
    current_answer_length: int | None = None
    baseline_deviation_ratio: float | None = None
    baseline_signal_counts: dict[str, int] = Field(default_factory=dict)
    current_signal_counts: dict[str, int] = Field(default_factory=dict)
    signal_deviation_ratios: dict[str, float] = Field(default_factory=dict)


class AuditRunItem(BaseModel):
    run_id: str
    role: str
    doc_type: str
    status: str
    created_at: str
    updated_at: str


class AuditEventItem(BaseModel):
    event_id: int
    event_type: str
    payload: dict[str, object]
    created_at: str


class AuditCheckpointItem(BaseModel):
    checkpoint_id: int
    checkpoint_index: int
    state: dict[str, object]
    created_at: str


class AuditResponse(BaseModel):
    run: AuditRunItem
    events: list[AuditEventItem]
    checkpoints: list[AuditCheckpointItem]


class ReviewQueueItem(BaseModel):
    run_id: str
    role: str
    doc_type: str
    status: str
    created_at: str
    updated_at: str
    aai_index: int | None = None
    review_priority_score: int | None = None
    priority_band: str = "unknown"
    priority_reasons: list[str] = Field(default_factory=list)
    assigned_reviewer: str = ""


class ReviewDecisionRequest(BaseModel):
    reviewer_name: str = "reviewer"
    decision: str
    rationale: str
    override_outcome: str | None = None


class ReviewerLoginRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    access_key: str = Field(min_length=1, max_length=500)


@app.post("/review/auth/login")
def reviewer_login(request: ReviewerLoginRequest) -> dict[str, str]:
    auth_key = _reviewer_auth_key()
    if not auth_key:
        raise HTTPException(status_code=503, detail="Reviewer authentication is not configured")
    if not hmac.compare_digest(request.access_key, auth_key):
        raise HTTPException(status_code=401, detail="Invalid reviewer credentials")
    reviewer = request.reviewer.strip()
    return {"reviewer": reviewer, "token": _issue_reviewer_token(reviewer)}


@app.get("/review/auth/status")
def reviewer_auth_status() -> dict[str, bool]:
    return {"configured": bool(_reviewer_auth_key())}


class ReviewDecisionItem(BaseModel):
    review_id: int
    run_id: str
    reviewer_name: str
    decision: str
    rationale: str
    override_outcome: str | None = None
    created_at: str
    updated_at: str


class StartRunRequest(BaseModel):
    role: str = "backend_engineer"
    doc_type: str = "role_description"
    role_description: str = ""
    integrity: IntegrityRequestItem | None = None
    interview_token: str = ""


class CreateInterviewRequest(BaseModel):
    candidate_name: str
    candidate_email: str
    role_id: str
    job_offer: str = ""
    scheduled_at: str
    expires_at: str


class ReviewerAssignmentRequest(BaseModel):
    reviewer: str


class IntegrityDispositionRequest(BaseModel):
    reviewer: str = "reviewer"
    disposition: str
    rationale: str


class FollowUpRequest(BaseModel):
    reviewer: str = "reviewer"
    requested_action: str = Field(min_length=1, max_length=2000)


class FollowUpStatusRequest(BaseModel):
    reviewer: str = "reviewer"
    status: str
    note: str = ""


class RoleConfigurationRequest(BaseModel):
    decision_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    recommendation_low_max: float = Field(default=0.40, ge=0.0, le=1.0)
    recommendation_high_min: float = Field(default=0.70, ge=0.0, le=1.0)
    conclusion_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    max_turns: int = Field(default=3, ge=3, le=10)
    interviewer_persona: str = Field(default="", max_length=500)
    question_prompt: str = Field(default="", max_length=2000)


class IntegrityConfigurationRequest(BaseModel):
    signal_weights: dict[str, int] = Field(
        default_factory=lambda: {"focus": 3, "timing": 3, "input": 3, "motion": 3, "content": 3}
    )
    max_penalty: int = Field(default=100, ge=0, le=100)
    ai_text_cap: float = Field(default=0.1, ge=0, le=0.1)


class InterviewListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class PublicInterviewResponse(BaseModel):
    interview_id: str
    candidate_name: str
    role_id: str
    role_title: str
    role_description: str
    job_offer: str
    scheduled_at: str
    expires_at: str
    status: str
    integrity_preferences: dict[str, Any] | None = None


class SubmitAnswerRequest(BaseModel):
    run_id: str
    answer: str
    role: str | None = None
    doc_type: str | None = None
    integrity: IntegrityRequestItem | None = None


class SubmitAnswerResponse(BaseModel):
    run_id: str
    role: str
    doc_type: str
    question: str | None
    question_index: int
    total_questions: int
    completed: bool
    grounded_context: list[GroundedContextItem]
    citation_list: list[CitationItem]
    review_state: ReviewStateItem
    graph_state: GraphStateItem
    integrity_state: IntegrityStateItem
    warmup: bool = False


class ReviewDecisionResponse(BaseModel):
    review: ReviewDecisionItem
    run: AuditRunItem


class AdminRoleItem(BaseModel):
    role_id: str
    title: str
    location: str
    description: str
    created_at: str
    updated_at: str


class CorpusDocumentItem(BaseModel):
    doc_id: str
    filename: str
    doc_type: str
    role: str
    status: str
    chunk_count: int
    created_at: str
    updated_at: str
    last_ingested_at: str | None
    error: str | None


class CreateRoleRequest(BaseModel):
    role_id: str
    title: str
    location: str
    description: str


class CreateAnalyticsSnapshotRequest(BaseModel):
    label: str = ""
    policy_version: str = DEFAULT_POLICY_VERSION
    prompt_version: str = DEFAULT_PROMPT_VERSION


class AnalyticsSnapshotSummaryItem(BaseModel):
    snapshot_id: int
    label: str
    policy_version: str
    prompt_version: str
    created_at: str
    generated_at: str | None = None


class AnalyticsSnapshotDetailResponse(BaseModel):
    snapshot_id: int
    label: str
    policy_version: str
    prompt_version: str
    created_at: str
    snapshot: dict[str, Any]
    llm_trace_rollup: dict[str, Any] | None = None


class AnalyticsComparisonResponse(BaseModel):
    baseline_snapshot_id: int
    candidate_snapshot_id: int
    comparison: dict[str, Any]


class AnalyticsSnapshotSyncRequest(BaseModel):
    label: str = ""
    policy_version: str = DEFAULT_POLICY_VERSION
    prompt_version: str = DEFAULT_PROMPT_VERSION


class AnalyticsSnapshotSyncResponse(BaseModel):
    job_type: str
    status: str
    snapshot_id: int
    label: str
    policy_version: str
    prompt_version: str
    created_at: str


class DriftCheckRequest(BaseModel):
    baseline_snapshot_id: int | None = None
    candidate_snapshot_id: int | None = None
    score_drop_threshold: float = 0.03
    override_increase_threshold: float = 0.05
    fairness_score_delta_threshold: float = 0.08
    fairness_override_delta_threshold: float = 0.1


class DriftCheckResponse(BaseModel):
    evaluation_id: int
    job_type: str
    status: str
    baseline_snapshot_id: int
    candidate_snapshot_id: int
    thresholds: dict[str, Any]
    comparison: dict[str, Any]
    breaches: list[dict[str, Any]]
    llm_trace_rollup: dict[str, Any] | None = None
    evaluated_at: str


class AnalyticsEvaluationSummaryItem(BaseModel):
    evaluation_id: int
    evaluation_type: str
    status: str
    baseline_snapshot_id: int | None
    candidate_snapshot_id: int | None
    created_at: str


class AnalyticsEvaluationDetailResponse(BaseModel):
    evaluation_id: int
    evaluation_type: str
    status: str
    baseline_snapshot_id: int | None
    candidate_snapshot_id: int | None
    thresholds: dict[str, Any]
    result: dict[str, Any]
    llm_trace_rollup: dict[str, Any] | None = None
    created_at: str


class LlmFallbackTrendPoint(BaseModel):
    evaluation_id: int
    created_at: str
    status: str
    baseline_snapshot_id: int | None
    candidate_snapshot_id: int | None
    baseline_fallback_rate: float
    candidate_fallback_rate: float
    fallback_rate_delta: float
    observed_turn_count_delta: int


class AnalyticsEvaluationTrendResponse(BaseModel):
    evaluation_count: int
    average_baseline_fallback_rate: float
    average_candidate_fallback_rate: float
    average_fallback_rate_delta: float
    max_candidate_fallback_rate: float
    points: list[LlmFallbackTrendPoint]


@dataclass
class RunContext:
    graph: InterviewGraph
    role: str
    doc_type: str
    interview_id: str | None = None
    warmup_pending: bool = True


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "agent" / "fixtures" / "corpus.json"
RETRIEVAL_SERVICE = GroundedRetrievalService.from_environment(FIXTURE_PATH)
set_retrieval_service(RETRIEVAL_SERVICE)


def _role_description_doc_id(role_id: str) -> str:
    digest = hashlib.sha256(role_id.encode("utf-8")).hexdigest()[:20]
    return f"admin-role-description-{digest}"


def _index_role_description(role_id: str, description: str) -> None:
    content = description.strip()
    if not content:
        return
    RETRIEVAL_SERVICE.ingest_document(
        CorpusDocument(
            doc_id=_role_description_doc_id(role_id),
            doc_type="role_description",
            role=role_id,
            content=content,
        )
    )


def _index_saved_role_descriptions() -> None:
    for role in PERSISTENCE.list_roles():
        _index_role_description(role.role_id, role.description)


CORPUS_MANAGER = CorpusDocumentManager(
    RETRIEVAL_SERVICE,
    Path(__file__).resolve().parents[2] / "data" / "admin_corpus",
)
INTERVIEW_DATA_PATH = Path(
    os.getenv(
        "AI_INTERVIEWER_INTERVIEW_DB_PATH",
        str(Path(__file__).resolve().parents[2] / "data" / "interviews.sqlite3"),
    )
)
INTERVIEW_REPOSITORY = InterviewRepository(
    INTERVIEW_DATA_PATH,
    postgres_dsn=(
        os.getenv("AI_INTERVIEWER_POSTGRES_DSN", "").strip()
        if os.getenv("AI_INTERVIEWER_DB_BACKEND", "sqlite").strip().lower() == "postgres"
        else None
    ),
)
RUN_STATE: dict[str, RunContext] = {}


def _checkpointed_graph_for_app():
    if os.getenv("AI_INTERVIEWER_DB_BACKEND", "sqlite").strip().lower() == "postgres":
        return get_checkpointed_graph(
            dsn=os.getenv("AI_INTERVIEWER_LANGGRAPH_POSTGRES_DSN", "").strip()
        )
    persistence_path = getattr(PERSISTENCE, "db_path", None)
    checkpoint_path = (
        persistence_path.with_name(
            f"{persistence_path.stem}.langgraph{persistence_path.suffix}"
        )
        if persistence_path is not None
        else None
    )
    return get_checkpointed_graph(db_path=checkpoint_path)


def _graph_thread_config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}}


def _sync_interview_graph_from_langgraph(
    run_context: RunContext, state: dict[str, Any]
) -> None:
    graph_state = dict(state)
    graph_state["final_route"] = state.get("route") or state.get("final_route")
    graph_state["pending_question"] = state.get("question")
    run_context.graph._state = InterviewGraphState.from_dict(graph_state)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run/start", response_model=StartRunResponse)
def start_run(request: StartRunRequest | None = None) -> StartRunResponse:
    start_request = request or StartRunRequest()
    interview: InterviewRecord | None = None
    if start_request.interview_token:
        interview = INTERVIEW_REPOSITORY.resolve_token(start_request.interview_token)
        if interview is None:
            raise HTTPException(status_code=404, detail="Interview link is invalid or revoked")
        if interview.status not in {"active", "in_progress"}:
            raise HTTPException(status_code=410, detail=f"Interview is not available ({interview.status})")
        start_request.role = interview.role_id
        start_request.doc_type = "role_description"
        if interview.status == "in_progress":
            run_id = interview.active_run_id or next(
                (
                    existing_run_id
                    for existing_run_id, context in RUN_STATE.items()
                    if context.interview_id == interview.interview_id
                ),
                None,
            )
            run_context = (
                RUN_STATE.get(run_id) or _restore_run_context(run_id)
                if run_id
                else None
            )
            if run_id and run_context:
                if interview.active_run_id != run_id:
                    INTERVIEW_REPOSITORY.set_active_run(interview.interview_id, run_id)
                run_context.interview_id = interview.interview_id
                RUN_STATE[run_id] = run_context
                if run_context.graph._state.final_route in {"conclude", "escalate"}:
                    INTERVIEW_REPOSITORY.set_status(interview.interview_id, "completed")
                    raise HTTPException(status_code=410, detail="Interview is already completed")
                question = (
                    "Warm-up: tell us briefly about a recent project or problem you worked on."
                    if run_context.warmup_pending
                    else run_context.graph.current_question()
                )
                question_index = (
                    0
                    if run_context.warmup_pending
                    else min(
                        run_context.graph._state.turn_index + 1,
                        run_context.graph.total_questions(),
                    )
                )
                resume_grounded_context = (
                    []
                    if run_context.warmup_pending
                    else _build_grounded_context(
                        query_text=question,
                        role=run_context.role,
                        doc_type=run_context.doc_type,
                        competency=run_context.graph._state.current_competency,
                    )
                )
                graph_snapshot = run_context.graph.snapshot()
                return StartRunResponse(
                    run_id=run_id,
                    role=run_context.role,
                    doc_type=run_context.doc_type,
                    question=question,
                    question_index=question_index,
                    total_questions=run_context.graph.total_questions(),
                    completed=False,
                    grounded_context=resume_grounded_context,
                    citation_list=_build_citation_list(resume_grounded_context),
                    review_state=_build_review_state(graph_snapshot, completed=False),
                    graph_state=_build_graph_state(graph_snapshot),
                    integrity_state=_build_integrity_state(start_request.integrity),
                    warmup=run_context.warmup_pending,
                )
    role_definition = PERSISTENCE.load_role(start_request.role)
    role_description = (
        role_definition.description
        if role_definition is not None
        else start_request.role_description.strip()
    )
    if interview is not None and interview.job_offer.strip():
        role_description = "\n\n".join(
            item
            for item in (
                role_description,
                f"Interview context: {interview.job_offer.strip()}",
            )
            if item
        )
    start_request.role_description = role_description
    _index_role_description(
        start_request.role,
        role_definition.description if role_definition is not None else role_description,
    )
    role_configuration = INTERVIEW_REPOSITORY.get_role_configuration(start_request.role)
    prompt_context = "\n\n".join(
        item for item in (
            start_request.role_description.strip(),
            f"Interviewer persona: {role_configuration['interviewer_persona']}"
            if role_configuration["interviewer_persona"] else "",
            f"Question guidance: {role_configuration['question_prompt']}"
            if role_configuration["question_prompt"] else "",
        ) if item
    )
    integrity_state = _build_integrity_state(start_request.integrity)

    run_id = f"iv_{uuid4().hex[:6]}"
    graph = InterviewGraph(
        role=start_request.role,
        doc_type=start_request.doc_type,
        retrieval_service=RETRIEVAL_SERVICE,
    )
    graph._state.role_description = prompt_context
    graph._state.max_turns = role_configuration["max_turns"]
    graph._state.decision_threshold = role_configuration["decision_threshold"]
    graph._state.recommendation_low_max = role_configuration["recommendation_low_max"]
    graph._state.recommendation_high_min = role_configuration["recommendation_high_min"]
    graph._state.conclusion_threshold = role_configuration["conclusion_threshold"]
    graph._state.confidence_threshold = role_configuration["confidence_threshold"]
    RUN_STATE[run_id] = RunContext(
        graph=graph,
        role=start_request.role,
        doc_type=start_request.doc_type,
        interview_id=interview.interview_id if interview is not None else None,
    )

    warmup_question = "Warm-up: tell us briefly about a recent project or problem you worked on."
    grounded_context: list[GroundedContextItem] = []

    start_payload = {
        "run_id": run_id,
        "role": start_request.role,
        "doc_type": start_request.doc_type,
        "question": warmup_question,
        "assigned_reviewer": interview.reviewer if interview is not None else "",
    }
    PERSISTENCE.save_run_start(
        run_id=run_id,
        role=start_request.role,
        doc_type=start_request.doc_type,
        state=graph.export_state().state,
        payload={
            **start_payload,
            "grounded_context": [item.model_dump() for item in grounded_context],
            "citation_list": [item.model_dump() for item in _build_citation_list(grounded_context)],
            "review_state": _build_review_state(graph.snapshot(), completed=False).model_dump(),
            "graph_state": _build_graph_state(graph.snapshot()).model_dump(),
            "integrity_state": integrity_state.model_dump(),
        },
    )
    if interview is not None:
        INTERVIEW_REPOSITORY.set_active_run(interview.interview_id, run_id)

    return StartRunResponse(
        run_id=run_id,
        role=start_request.role,
        doc_type=start_request.doc_type,
        question=warmup_question,
        question_index=0,
        total_questions=graph.total_questions(),
        completed=False,
        grounded_context=grounded_context,
        citation_list=_build_citation_list(grounded_context),
        review_state=_build_review_state(graph.snapshot(), completed=False),
        graph_state=_build_graph_state(graph.snapshot()),
        integrity_state=integrity_state,
        warmup=True,
    )


@app.post("/run/answer", response_model=SubmitAnswerResponse)
def submit_answer(request: SubmitAnswerRequest) -> SubmitAnswerResponse:
    if not request.answer.strip():
        raise HTTPException(status_code=400, detail="Answer cannot be empty")

    run_context = RUN_STATE.get(request.run_id)
    if run_context is None:
        run_context = _restore_run_context(request.run_id)
        if run_context is None:
            raise HTTPException(status_code=404, detail="Run not found")
        RUN_STATE[request.run_id] = run_context

    if run_context.warmup_pending:
        effective_role = request.role or run_context.role
        effective_doc_type = request.doc_type or run_context.doc_type
        run_context.graph.set_filters(effective_role, effective_doc_type)
        run_context.role = effective_role
        run_context.doc_type = effective_doc_type
        integrity_state = _build_integrity_state(request.integrity)
        warmup_payload = {
            "run_id": request.run_id,
            "role": effective_role,
            "doc_type": effective_doc_type,
            "event_type": "warmup_completed",
            "warmup": True,
            "answer": request.answer,
            "answer_length": len(request.answer.strip()),
            "telemetry_events": [item.model_dump() for item in (request.integrity.telemetry_events if request.integrity else [])],
            "integrity_state": integrity_state.model_dump(),
        }
        graph_input = run_context.graph.export_state().state
        graph_input["answer"] = ""
        graph_input["question"] = None
        checkpointed_graph = _checkpointed_graph_for_app()
        config = _graph_thread_config(request.run_id)
        checkpointed_graph.invoke(graph_input, config)
        langgraph_state = dict(checkpointed_graph.get_state(config).values)
        _sync_interview_graph_from_langgraph(run_context, langgraph_state)
        run_context.warmup_pending = False
        first_question = str(langgraph_state.get("question") or "")
        grounded_context = _build_grounded_context(
            query_text=first_question,
            role=effective_role,
            doc_type=effective_doc_type,
            competency=run_context.graph._state.current_competency,
        )
        warmup_payload.update(
            {
                "question": first_question,
                "grounded_context": [item.model_dump() for item in grounded_context],
                "citation_list": [
                    item.model_dump() for item in _build_citation_list(grounded_context)
                ],
                "graph_state": _build_graph_state(run_context.graph.snapshot()).model_dump(),
            }
        )
        PERSISTENCE.save_turn(
            run_id=request.run_id,
            role=effective_role,
            doc_type=effective_doc_type,
            state=run_context.graph.export_state().state,
            payload=warmup_payload,
            checkpoint_index=0,
            completed=False,
        )
        return SubmitAnswerResponse(
            run_id=request.run_id,
            role=effective_role,
            doc_type=effective_doc_type,
            question=first_question,
            question_index=1,
            total_questions=run_context.graph.total_questions(),
            completed=False,
            grounded_context=grounded_context,
            citation_list=_build_citation_list(grounded_context),
            review_state=_build_review_state(run_context.graph.snapshot(), completed=False),
            graph_state=_build_graph_state(run_context.graph.snapshot()),
            integrity_state=integrity_state,
            warmup=False,
        )

    effective_role = request.role or run_context.role
    effective_doc_type = request.doc_type or run_context.doc_type
    effective_role_description = getattr(run_context.graph._state, "role_description", "")
    integrity_state = _with_integrity_baseline(
        request.run_id, request.answer, request.integrity
    )

    run_context.graph.set_filters(effective_role, effective_doc_type)
    run_context.graph._state.role_description = effective_role_description
    run_context.role = effective_role
    run_context.doc_type = effective_doc_type

    evaluated_competency = run_context.graph._state.current_competency
    grounded_context = _build_grounded_context(
        query_text=f"{evaluated_competency} {request.answer}",
        role=effective_role,
        doc_type=effective_doc_type,
        competency=evaluated_competency,
    )

    answered_question = run_context.graph.current_question()
    checkpointed_graph = _checkpointed_graph_for_app()
    config = _graph_thread_config(request.run_id)
    checkpoint = checkpointed_graph.get_state(config)
    if not checkpoint.values:
        initial_state = run_context.graph.export_state().state
        initial_state["question"] = run_context.graph._state.pending_question
        initial_state["answer"] = ""
        checkpointed_graph.invoke(initial_state, config)
        checkpoint = checkpointed_graph.get_state(config)
    if checkpoint.next == ("await_candidate",):
        checkpointed_graph.invoke(Command(resume=request.answer), config)
    elif checkpoint.next == ("evaluate",):
        if checkpoint.values.get("answer") != request.answer:
            raise HTTPException(
                status_code=409,
                detail="A previous answer is awaiting evaluation. Resubmit the same answer to retry it.",
            )
        checkpointed_graph.invoke(None, config)
    else:
        raise HTTPException(status_code=409, detail="Interview graph is not waiting for a candidate answer")
    graph_snapshot = checkpointed_graph.get_state(config)
    langgraph_state = dict(graph_snapshot.values)
    _sync_interview_graph_from_langgraph(run_context, langgraph_state)
    snapshot = run_context.graph.snapshot()
    persisted_state = run_context.graph.export_state().state
    step_completed = graph_snapshot.next == ("human_review",)
    step_question = None if step_completed else run_context.graph._state.pending_question
    step_question_index = (
        min(run_context.graph._state.turn_index, run_context.graph._state.max_turns)
        if step_completed
        else run_context.graph._state.turn_index + 1
    )
    step_total_questions = run_context.graph.total_questions()

    if step_completed:
        PERSISTENCE.save_turn(
            run_id=request.run_id,
            role=effective_role,
            doc_type=effective_doc_type,
            state=persisted_state,
            payload={
                "run_id": request.run_id,
                "role": effective_role,
                "doc_type": effective_doc_type,
                "competency": evaluated_competency,
                "answer": request.answer,
                "question": answered_question,
                "evaluation_score": persisted_state.get("last_evaluation_score"),
                "evaluation_evidence": persisted_state.get("last_evaluation_evidence", []),
                "evaluation_source_refs": persisted_state.get("last_evaluation_source_refs", []),
                "question_index": step_question_index,
                "completed": True,
                "grounded_context": [item.model_dump() for item in grounded_context],
                "citation_list": [
                    item.model_dump() for item in _build_citation_list(grounded_context)
                ],
                "review_state": _build_review_state(snapshot, completed=True).model_dump(),
                "graph_state": _build_graph_state(snapshot).model_dump(),
                "integrity_state": integrity_state.model_dump(),
            },
            checkpoint_index=step_question_index,
            completed=True,
        )
        if run_context.interview_id:
            INTERVIEW_REPOSITORY.set_status(run_context.interview_id, "completed")
            INTERVIEW_REPOSITORY.record_audit(
                "interview.completed", run_context.interview_id, {"run_id": request.run_id}
            )
        return SubmitAnswerResponse(
            run_id=request.run_id,
            role=effective_role,
            doc_type=effective_doc_type,
            question=None,
            question_index=step_question_index,
            total_questions=step_total_questions,
            completed=True,
            grounded_context=grounded_context,
            citation_list=_build_citation_list(grounded_context),
            review_state=_build_review_state(run_context.graph.snapshot(), completed=True),
            graph_state=_build_graph_state(run_context.graph.snapshot()),
            integrity_state=integrity_state,
        )

    PERSISTENCE.save_turn(
        run_id=request.run_id,
        role=effective_role,
        doc_type=effective_doc_type,
        state=persisted_state,
        payload={
            "run_id": request.run_id,
            "role": effective_role,
            "doc_type": effective_doc_type,
            "competency": evaluated_competency,
            "answer": request.answer,
            "question": answered_question,
            "evaluation_score": persisted_state.get("last_evaluation_score"),
            "evaluation_evidence": persisted_state.get("last_evaluation_evidence", []),
            "evaluation_source_refs": persisted_state.get("last_evaluation_source_refs", []),
            "question_index": step_question_index,
            "completed": False,
            "grounded_context": [item.model_dump() for item in grounded_context],
            "citation_list": [item.model_dump() for item in _build_citation_list(grounded_context)],
            "review_state": _build_review_state(snapshot, completed=False).model_dump(),
            "graph_state": _build_graph_state(snapshot).model_dump(),
            "integrity_state": integrity_state.model_dump(),
        },
        checkpoint_index=step_question_index,
        completed=False,
    )

    return SubmitAnswerResponse(
        run_id=request.run_id,
        role=effective_role,
        doc_type=effective_doc_type,
        question=step_question,
        question_index=step_question_index,
        total_questions=step_total_questions,
        completed=False,
        grounded_context=grounded_context,
        citation_list=_build_citation_list(grounded_context),
        review_state=_build_review_state(run_context.graph.snapshot(), completed=False),
        graph_state=_build_graph_state(run_context.graph.snapshot()),
        integrity_state=integrity_state,
    )


@app.get("/runs/{run_id}/audit", response_model=AuditResponse)
def get_run_audit(run_id: str, request: Request) -> AuditResponse:
    _authenticated_reviewer(request)
    bundle = PERSISTENCE.load_audit_bundle(run_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run_record = bundle["run"]
    return AuditResponse(
        run=AuditRunItem(
            run_id=run_record.run_id,
            role=run_record.role,
            doc_type=run_record.doc_type,
            status=run_record.status,
            created_at=run_record.created_at,
            updated_at=run_record.updated_at,
        ),
        events=[
            AuditEventItem(
                event_id=event.event_id,
                event_type=event.event_type,
                payload=event.payload,
                created_at=event.created_at,
            )
            for event in bundle["events"]
        ],
        checkpoints=[
            AuditCheckpointItem(
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_index=checkpoint.checkpoint_index,
                state=checkpoint.state,
                created_at=checkpoint.created_at,
            )
            for checkpoint in bundle["checkpoints"]
        ],
    )


@app.get("/review/queue", response_model=list[ReviewQueueItem])
def get_review_queue(request: Request) -> list[ReviewQueueItem]:
    _authenticated_reviewer(request)
    queue_items = []
    for item in PERSISTENCE.list_review_queue():
        queue_items.append(
            ReviewQueueItem(
                run_id=item.run_id,
                role=item.role,
                doc_type=item.doc_type,
                status=item.status,
                created_at=item.created_at,
                updated_at=item.updated_at,
                **_review_priority(item.run_id),
                assigned_reviewer=_assigned_reviewer(item.run_id),
            )
        )
    return sorted(
        queue_items,
        key=lambda item: (
            item.review_priority_score is not None,
            item.review_priority_score if item.review_priority_score is not None else -1,
            item.updated_at,
        ),
        reverse=True,
    )


def _review_priority(run_id: str) -> dict[str, Any]:
    integrity_state = None
    for event in PERSISTENCE.load_events(run_id):
        candidate = event.payload.get("integrity_state")
        if isinstance(candidate, dict):
            integrity_state = candidate

    if integrity_state is None:
        return {"aai_index": None, "review_priority_score": None, "priority_band": "unknown"}

    aai_index = integrity_state.get("aai_index")
    if not isinstance(aai_index, int):
        return {"aai_index": None, "review_priority_score": None, "priority_band": "unknown"}

    priority_score = max(0, min(100, aai_index))
    if priority_score < 25:
        priority_band = "none"
    elif priority_score < 50:
        priority_band = "low"
    elif priority_score < 75:
        priority_band = "elevated"
    else:
        priority_band = "high"

    reasons = []
    for signal in integrity_state.get("signal_breakdown", []):
        if not isinstance(signal, dict) or signal.get("suppressed"):
            continue
        count = signal.get("event_count", 0)
        family = signal.get("signal_family")
        if isinstance(count, int) and count > 0 and isinstance(family, str):
            reasons.append(f"{family}: {count}")
    return {
        "aai_index": aai_index,
        "review_priority_score": priority_score,
        "priority_band": priority_band,
        "priority_reasons": reasons,
    }


def _assigned_reviewer(run_id: str) -> str:
    for event in PERSISTENCE.load_events(run_id):
        if event.event_type != "run_started":
            continue
        reviewer = event.payload.get("assigned_reviewer")
        return reviewer.strip() if isinstance(reviewer, str) else ""
    return ""


def _require_assigned_reviewer(run_id: str, reviewer: str) -> str:
    assigned = _assigned_reviewer(run_id)
    current = reviewer.strip() or "reviewer"
    if assigned and assigned.casefold() != current.casefold():
        raise HTTPException(status_code=403, detail="Run is assigned to another reviewer")
    return current


@app.post("/runs/{run_id}/review", response_model=ReviewDecisionResponse)
def submit_review(
    run_id: str, request: ReviewDecisionRequest, http_request: Request
) -> ReviewDecisionResponse:
    if not request.rationale.strip():
        raise HTTPException(status_code=400, detail="Rationale cannot be empty")

    if request.decision not in {"approved", "overridden"}:
        raise HTTPException(status_code=400, detail="Decision must be approved or overridden")
    if request.decision == "overridden" and request.override_outcome not in {"conclude", "escalate"}:
        raise HTTPException(
            status_code=400,
            detail="An override outcome of conclude or escalate is required",
        )
    if request.decision == "approved" and request.override_outcome is not None:
        raise HTTPException(status_code=400, detail="Approved reviews cannot include an override outcome")
    authenticated_reviewer = _authenticated_reviewer(http_request)
    reviewer_name = _require_assigned_reviewer(
        run_id, authenticated_reviewer or request.reviewer_name
    )

    checkpointed_graph = _checkpointed_graph_for_app()
    config = _graph_thread_config(run_id)
    graph_checkpoint = checkpointed_graph.get_state(config)
    if graph_checkpoint.next == ("human_review",):
        checkpointed_graph.invoke(
            Command(
                resume={
                    "decision": request.decision,
                    "rationale": request.rationale.strip(),
                    "override_outcome": request.override_outcome,
                }
            ),
            config,
        )
        graph_checkpoint = checkpointed_graph.get_state(config)
        if not graph_checkpoint.values.get("completed"):
            raise HTTPException(status_code=409, detail="LangGraph review interrupt did not complete")

    try:
        review = PERSISTENCE.save_review_decision(
            run_id=run_id,
            reviewer_name=reviewer_name,
            decision=request.decision,
            rationale=request.rationale.strip(),
            override_outcome=request.override_outcome,
        )
        INTERVIEW_REPOSITORY.record_audit(
            "review.decision", run_id,
            {
                "reviewer": reviewer_name,
                "decision": request.decision,
                "override_outcome": request.override_outcome,
            },
            actor=reviewer_name,
        )
    except RuntimeError:
        raise HTTPException(status_code=409, detail="Run is already finalized") from None
    except ValueError:
        raise HTTPException(status_code=404, detail="Run not found") from None

    run_record = PERSISTENCE.load_run(run_id)
    if run_record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    graph_report = graph_checkpoint.values.get("report")
    final_route = (
        graph_report.get("route")
        if isinstance(graph_report, dict) and isinstance(graph_report.get("route"), str)
        else review.override_outcome
    ) or next(
        (event.payload.get("graph_state", {}).get("final_route")
         for event in reversed(PERSISTENCE.load_events(run_id))
         if isinstance(event.payload.get("graph_state"), dict)
         and event.payload.get("graph_state", {}).get("final_route")),
        "escalate",
    )
    PERSISTENCE.materialize_report(run_id, final_route)
    run_record = PERSISTENCE.load_run(run_id) or run_record

    return ReviewDecisionResponse(
        review=ReviewDecisionItem(
            review_id=review.review_id,
            run_id=review.run_id,
            reviewer_name=review.reviewer_name,
            decision=review.decision,
            rationale=review.rationale,
            override_outcome=review.override_outcome,
            created_at=review.created_at,
            updated_at=review.updated_at,
        ),
        run=AuditRunItem(
            run_id=run_record.run_id,
            role=run_record.role,
            doc_type=run_record.doc_type,
            status=run_record.status,
            created_at=run_record.created_at,
            updated_at=run_record.updated_at,
        ),
    )


@app.get("/runs/{run_id}/integrity-disposition")
def get_integrity_disposition(run_id: str, request: Request) -> dict[str, Any] | None:
    _authenticated_reviewer(request)
    if PERSISTENCE.load_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return INTERVIEW_REPOSITORY.get_integrity_disposition(run_id)


@app.put("/runs/{run_id}/integrity-disposition")
def save_integrity_disposition(
    run_id: str, request: IntegrityDispositionRequest, http_request: Request
) -> dict[str, Any]:
    authenticated_reviewer = _authenticated_reviewer(http_request)
    if PERSISTENCE.load_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if request.disposition not in {"confirmed", "dismissed", "inconclusive"}:
        raise HTTPException(status_code=400, detail="Unsupported integrity disposition")
    if not request.rationale.strip():
        raise HTTPException(status_code=400, detail="Rationale cannot be empty")
    reviewer = _require_assigned_reviewer(
        run_id, authenticated_reviewer or request.reviewer
    )
    result = INTERVIEW_REPOSITORY.save_integrity_disposition(
        run_id, reviewer, request.disposition, request.rationale
    )
    INTERVIEW_REPOSITORY.record_audit(
        "review.integrity_disposition", run_id,
        {"disposition": request.disposition, "rationale": request.rationale.strip()},
        actor=reviewer,
    )
    return result


@app.get("/runs/{run_id}/follow-up")
def get_follow_up(run_id: str, request: Request) -> dict[str, Any] | None:
    _authenticated_reviewer(request)
    if PERSISTENCE.load_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return INTERVIEW_REPOSITORY.get_follow_up(run_id)


@app.post("/runs/{run_id}/follow-up")
def request_follow_up(
    run_id: str, request: FollowUpRequest, http_request: Request
) -> dict[str, Any]:
    authenticated_reviewer = _authenticated_reviewer(http_request)
    if PERSISTENCE.load_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    reviewer = _require_assigned_reviewer(
        run_id, authenticated_reviewer or request.reviewer
    )
    result = INTERVIEW_REPOSITORY.save_follow_up(run_id, reviewer, request.requested_action)
    INTERVIEW_REPOSITORY.record_audit(
        "review.follow_up.requested", run_id,
        {"reviewer": reviewer, "requested_action": request.requested_action.strip()},
        actor=reviewer,
    )
    return result


@app.patch("/runs/{run_id}/follow-up")
def update_follow_up(
    run_id: str, request: FollowUpStatusRequest, http_request: Request
) -> dict[str, Any]:
    authenticated_reviewer = _authenticated_reviewer(http_request)
    if PERSISTENCE.load_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if request.status not in {"requested", "in_progress", "completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Unsupported follow-up status")
    reviewer = _require_assigned_reviewer(
        run_id, authenticated_reviewer or request.reviewer
    )
    try:
        result = INTERVIEW_REPOSITORY.update_follow_up(run_id, reviewer, request.status, request.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="Follow-up not found") from None
    INTERVIEW_REPOSITORY.record_audit(
        "review.follow_up.updated", run_id,
        {"reviewer": reviewer, "status": request.status, "note": request.note.strip()},
        actor=reviewer,
    )
    return result


@app.post("/runs/{run_id}/recommendation-letter")
def generate_recommendation_letter(
    run_id: str, request: Request, reviewer: str = "reviewer"
) -> dict[str, Any]:
    run = PERSISTENCE.load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "finalized":
        raise HTTPException(status_code=409, detail="Finalize the review before generating a letter")
    review = PERSISTENCE.load_review_decision(run_id)
    if review is None:
        raise HTTPException(status_code=409, detail="Submit a final review before generating a letter")
    authenticated_reviewer = _authenticated_reviewer(request)
    reviewer_name = _require_assigned_reviewer(
        run_id, authenticated_reviewer or reviewer
    )
    events = PERSISTENCE.load_events(run_id)
    scores = [
        float(event.payload["evaluation_score"])
        for event in events
        if isinstance(event.payload.get("evaluation_score"), (int, float))
    ]
    average_score = sum(scores) / len(scores) if scores else 0.0
    outcome = review.override_outcome or next(
        (event.payload.get("graph_state", {}).get("final_route")
         for event in reversed(events)
         if isinstance(event.payload.get("graph_state"), dict)
         and event.payload.get("graph_state", {}).get("final_route")),
        "escalate",
    )
    recommendation = "recommend proceeding to the next stage" if outcome == "conclude" else "recommend additional review before proceeding"
    letter = (
        f"# Recommendation for {run.role}\n\n"
        f"This assessment was reviewed by {reviewer_name}.\n\n"
        f"The candidate completed an assessment for {run.role} with an average evaluated score of {average_score:.2f}. "
        f"The finalized outcome was **{outcome}**. Based on the recorded evidence, we {recommendation}.\n\n"
        f"Reviewer rationale: {review.rationale}\n"
    )
    return {"run_id": run_id, "reviewer": reviewer_name, "outcome": outcome, "content": letter}


@app.get("/runs/{run_id}/assessment.html", response_class=HTMLResponse)
def export_assessment_html(run_id: str, request: Request) -> HTMLResponse:
    _authenticated_reviewer(request)
    bundle = PERSISTENCE.load_audit_bundle(run_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run = bundle["run"]
    if run.status != "finalized":
        raise HTTPException(status_code=409, detail="Finalize the review before exporting the assessment")
    review = PERSISTENCE.load_review_decision(run_id)
    events = bundle["events"]
    scores = [
        float(event.payload["evaluation_score"])
        for event in events
        if isinstance(event.payload.get("evaluation_score"), (int, float))
    ]
    score_text = f"{sum(scores) / len(scores):.2f}" if scores else "n/a"
    review_text = review.rationale if review else "Pending human review"
    outcome = (review.override_outcome if review else None) or (
        next((event.payload.get("graph_state", {}).get("final_route") for event in reversed(events)
              if isinstance(event.payload.get("graph_state"), dict)), "pending")
    )
    body = f"""
    <!doctype html><html><head><meta charset='utf-8'><title>Assessment {html.escape(run_id)}</title>
    <style>body{{font-family:Arial,sans-serif;color:#172033;max-width:900px;margin:40px auto;padding:0 24px}}
    h1{{color:#0f766e}} .meta{{color:#526174}} section{{border-top:1px solid #d8dee8;padding:18px 0}}
    .score{{font-size:2rem;font-weight:700}} pre{{white-space:pre-wrap;background:#f4f7fb;padding:14px;border-radius:8px}}
    @media print{{body{{margin:20px auto}}}}</style></head><body>
    <h1>Interview Assessment</h1><p class='meta'>Run: {html.escape(run_id)} | Role: {html.escape(run.role)} | Status: {html.escape(run.status)}</p>
    <section><h2>Summary</h2><p class='score'>{score_text}</p><p>Final outcome: <strong>{html.escape(str(outcome))}</strong></p></section>
    <section><h2>Reviewer rationale</h2><p>{html.escape(review_text)}</p></section>
    <section><h2>Transcript</h2>{''.join(f"<article><h3>{html.escape(str(event.payload.get('question', '')))}</h3><p>{html.escape(str(event.payload.get('answer', '')))}</p></article>" for event in events if event.payload.get('answer'))}</section>
    </body></html>
    """
    return HTMLResponse(content=body)


@app.post("/admin/roles", response_model=AdminRoleItem)
def create_admin_role(request: CreateRoleRequest) -> AdminRoleItem:
    role = PERSISTENCE.save_role(
        role_id=request.role_id,
        title=request.title,
        location=request.location,
        description=request.description,
    )
    _index_role_description(role.role_id, role.description)
    INTERVIEW_REPOSITORY.record_audit("role.save", role.role_id, {"title": role.title})
    return AdminRoleItem(
        role_id=role.role_id,
        title=role.title,
        location=role.location,
        description=role.description,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@app.get("/admin/roles", response_model=list[AdminRoleItem])
def list_admin_roles() -> list[AdminRoleItem]:
    roles = PERSISTENCE.list_roles()
    return [
        AdminRoleItem(
            role_id=item.role_id,
            title=item.title,
            location=item.location,
            description=item.description,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in roles
    ]


@app.get("/admin/roles/{role_id}", response_model=AdminRoleItem)
def get_admin_role(role_id: str) -> AdminRoleItem:
    role = PERSISTENCE.load_role(role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return AdminRoleItem(
        role_id=role.role_id,
        title=role.title,
        location=role.location,
        description=role.description,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@app.get("/admin/roles/{role_id}/configuration")
def get_admin_role_configuration(role_id: str) -> dict[str, Any]:
    return INTERVIEW_REPOSITORY.get_role_configuration(role_id)


@app.put("/admin/roles/{role_id}/configuration")
def save_admin_role_configuration(
    role_id: str, request: RoleConfigurationRequest
) -> dict[str, Any]:
    if request.recommendation_low_max >= request.recommendation_high_min:
        raise HTTPException(
            status_code=400,
            detail="recommendation_low_max must be lower than recommendation_high_min",
        )
    config = INTERVIEW_REPOSITORY.save_role_configuration(role_id, request.model_dump())
    INTERVIEW_REPOSITORY.record_audit("role.configuration.update", role_id)
    return config


@app.get("/admin/integrity/configuration")
def get_integrity_configuration() -> dict[str, Any]:
    stored = INTERVIEW_REPOSITORY.get_setting("integrity")
    if not stored:
        return IntegrityConfigurationRequest().model_dump()
    configuration = dict(stored)
    configuration.setdefault("max_penalty", 100)
    configuration["ai_text_cap"] = min(
        0.1, max(0.0, float(configuration.get("ai_text_cap", 0.1)))
    )
    return configuration


@app.put("/admin/integrity/configuration")
def save_integrity_configuration(
    request: IntegrityConfigurationRequest,
) -> dict[str, Any]:
    allowed = {"focus", "timing", "input", "motion", "content"}
    if set(request.signal_weights) - allowed:
        raise HTTPException(status_code=400, detail="Unsupported signal family in signal_weights")
    if any(weight < 0 or weight > 20 for weight in request.signal_weights.values()):
        raise HTTPException(status_code=400, detail="Signal weights must be between 0 and 20")
    config = INTERVIEW_REPOSITORY.save_setting("integrity", request.model_dump())
    INTERVIEW_REPOSITORY.record_audit("integrity.configuration.update", "integrity")
    return config


@app.get("/admin/corpus/documents", response_model=list[CorpusDocumentItem])
def list_corpus_documents() -> list[CorpusDocumentItem]:
    return [_corpus_document_to_item(item) for item in CORPUS_MANAGER.list_documents()]


@app.get("/admin/corpus/chunks/{chunk_id}")
def get_corpus_chunk(chunk_id: str) -> dict[str, Any]:
    chunk = RETRIEVAL_SERVICE.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Corpus chunk not found")
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "doc_type": chunk.doc_type,
        "role": chunk.role,
        "text": chunk.text,
        "metadata": chunk.metadata,
    }


@app.post("/admin/corpus/documents", response_model=CorpusDocumentItem)
async def upload_corpus_document(
    request: Request,
    filename: str,
    doc_type: str,
    role: str,
) -> CorpusDocumentItem:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_DOCUMENT_BYTES:
            raise HTTPException(
                status_code=413,
                detail="The uploaded document exceeds the 15 MB limit",
            )
        content.extend(chunk)
    try:
        record = CORPUS_MANAGER.upload(filename, bytes(content), doc_type, role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    INTERVIEW_REPOSITORY.record_audit("corpus.upload", record.doc_id, {"filename": record.filename, "status": record.status})
    return _corpus_document_to_item(record)


@app.post("/admin/corpus/documents/{doc_id}/ingest", response_model=CorpusDocumentItem)
def ingest_corpus_document(doc_id: str) -> CorpusDocumentItem:
    try:
        record = CORPUS_MANAGER.ingest(doc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Corpus document not found") from exc
    INTERVIEW_REPOSITORY.record_audit("corpus.ingest", doc_id, {"status": record.status})
    return _corpus_document_to_item(record)


@app.delete("/admin/corpus/documents/{doc_id}", status_code=204)
def delete_corpus_document(doc_id: str) -> Response:
    if not CORPUS_MANAGER.delete(doc_id):
        raise HTTPException(status_code=404, detail="Corpus document not found")
    INTERVIEW_REPOSITORY.record_audit("corpus.delete", doc_id)
    return Response(status_code=204)


@app.post("/admin/interviews")
def create_scheduled_interview(request: CreateInterviewRequest) -> dict[str, Any]:
    if not request.candidate_name.strip() or not request.candidate_email.strip() or not request.role_id.strip():
        raise HTTPException(status_code=400, detail="Candidate name, email, and role are required")
    try:
        record, token = INTERVIEW_REPOSITORY.create(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    INTERVIEW_REPOSITORY.record_audit("interview.create", record.interview_id, {"role_id": record.role_id})
    return {
        "interview": _interview_to_dict(record),
        "candidate_url": f"http://127.0.0.1:4174/?interview={token}",
    }


@app.get("/admin/interviews", response_model=InterviewListResponse)
def list_scheduled_interviews(
    search: str = "", status: str = "", limit: int = 50, offset: int = 0
) -> InterviewListResponse:
    items, total = INTERVIEW_REPOSITORY.list(
        search=search, status=status, limit=limit, offset=offset
    )
    return InterviewListResponse(
        items=[_interview_to_dict(item) for item in items],
        total=total,
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
    )


@app.get("/admin/interviews/export.csv")
def export_scheduled_interviews() -> Response:
    records: list[InterviewRecord] = []
    offset = 0
    while True:
        page, total = INTERVIEW_REPOSITORY.list(limit=200, offset=offset)
        records.extend(page)
        offset += len(page)
        if offset >= total or not page:
            break
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "interview_id", "candidate_name", "candidate_email", "role_id", "job_offer",
        "scheduled_at", "expires_at", "status", "reviewer", "created_at",
    ])
    for item in records:
        values = [
            item.interview_id, item.candidate_name, item.candidate_email, item.role_id,
            item.job_offer, item.scheduled_at, item.expires_at, item.status,
            item.reviewer, item.created_at,
        ]
        writer.writerow([_csv_safe(value) for value in values])
    INTERVIEW_REPOSITORY.record_audit("interview.export_csv", "interviews", {"count": len(records)})
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=scheduled-interviews.csv"},
    )


@app.post("/admin/interviews/bulk")
async def bulk_create_scheduled_interviews(request: Request) -> dict[str, Any]:
    try:
        text = (await request.body()).decode("utf-8-sig")
        reader = csv.DictReader(StringIO(text))
        required = {"candidate_name", "candidate_email", "role_id", "scheduled_at", "expires_at"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("CSV headers must include candidate_name,candidate_email,role_id,scheduled_at,expires_at; job_offer is optional")
        records = []
        for row in reader:
            record, token = INTERVIEW_REPOSITORY.create(
                candidate_name=row.get("candidate_name", ""),
                candidate_email=row.get("candidate_email", ""),
                role_id=row.get("role_id", ""),
                job_offer=row.get("job_offer", ""),
                scheduled_at=row.get("scheduled_at", ""),
                expires_at=row.get("expires_at", ""),
            )
            records.append({
                "interview": _interview_to_dict(record),
                "candidate_url": f"http://127.0.0.1:4174/?interview={token}",
            })
        INTERVIEW_REPOSITORY.record_audit("interview.bulk_create", "interviews", {"created": len(records)})
        return {"created": len(records), "items": records}
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/interviews/{interview_id}/activate")
def activate_scheduled_interview(interview_id: str) -> dict[str, Any]:
    try:
        record = INTERVIEW_REPOSITORY.set_status(interview_id, "active")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview not found") from exc
    INTERVIEW_REPOSITORY.record_audit("interview.activate", interview_id)
    record = _send_interview_invitation(interview_id, source="admin_activation")
    return _interview_to_dict(record)


@app.post("/admin/interviews/{interview_id}/send-invitation")
def send_scheduled_interview_invitation(interview_id: str) -> dict[str, Any]:
    try:
        record = INTERVIEW_REPOSITORY.get(interview_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview not found") from exc
    if record.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Interview must be active before sending an invitation",
        )
    if record.invitation_status not in {"not_sent", "failed", "logged"}:
        raise HTTPException(
            status_code=409,
            detail=f"Invitation status is {record.invitation_status}",
        )

    record = _send_interview_invitation(interview_id, source="admin_retry")
    if record.invitation_status == "failed":
        raise HTTPException(
            status_code=502,
            detail=record.invitation_error or "Invitation delivery failed",
        )
    return _interview_to_dict(record)


@app.post("/admin/interviews/{interview_id}/revoke")
def revoke_interview_link(interview_id: str) -> dict[str, Any]:
    try:
        record = INTERVIEW_REPOSITORY.set_status(interview_id, "revoked")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview not found") from exc
    INTERVIEW_REPOSITORY.record_audit("interview.revoke", interview_id)
    return _interview_to_dict(record)


@app.post("/admin/interviews/{interview_id}/regenerate-link")
def regenerate_interview_link(interview_id: str) -> dict[str, Any]:
    try:
        record, token = INTERVIEW_REPOSITORY.regenerate_link(interview_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Interview not found or already completed",
        ) from exc
    INTERVIEW_REPOSITORY.record_audit("interview.regenerate_link", interview_id)
    if record.status == "active":
        record = _send_interview_invitation(
            interview_id, source="admin_regenerate_link"
        )
    return {
        "interview": _interview_to_dict(record),
        "candidate_url": (
            f"http://127.0.0.1:4174/?interview={token}"
        ),
    }


@app.patch("/admin/interviews/{interview_id}/reviewer")
def assign_interview_reviewer(
    interview_id: str, request: ReviewerAssignmentRequest
) -> dict[str, Any]:
    try:
        record = INTERVIEW_REPOSITORY.assign_reviewer(interview_id, request.reviewer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview not found") from exc
    INTERVIEW_REPOSITORY.record_audit("interview.assign_reviewer", interview_id, {"reviewer": record.reviewer})
    return _interview_to_dict(record)


@app.get("/candidate/interviews/{token}", response_model=PublicInterviewResponse)
def get_candidate_interview(token: str) -> PublicInterviewResponse:
    record = INTERVIEW_REPOSITORY.resolve_token(token)
    if record is None:
        raise HTTPException(status_code=404, detail="Interview link is invalid or revoked")
    if record.status in {"expired", "revoked", "completed"}:
        raise HTTPException(status_code=410, detail=f"Interview link is {record.status}")
    role = PERSISTENCE.load_role(record.role_id)
    integrity_preferences = None
    if record.active_run_id:
        for event in reversed(PERSISTENCE.load_events(record.active_run_id)):
            integrity_state = event.payload.get("integrity_state")
            if isinstance(integrity_state, dict):
                integrity_preferences = {
                    "disclosure_accepted": integrity_state.get("disclosure_accepted", False),
                    "focus_telemetry_enabled": integrity_state.get(
                        "focus_telemetry_enabled", False
                    ),
                    "suppressed_signal_families": integrity_state.get(
                        "suppressed_signal_families", []
                    ),
                }
                break
    return PublicInterviewResponse(
        interview_id=record.interview_id,
        candidate_name=record.candidate_name,
        role_id=record.role_id,
        role_title=role.title if role else record.role_id,
        role_description=role.description if role else "",
        job_offer=record.job_offer,
        scheduled_at=record.scheduled_at,
        expires_at=record.expires_at,
        status=record.status,
        integrity_preferences=integrity_preferences,
    )


def _interview_to_dict(record: InterviewRecord) -> dict[str, Any]:
    return {
        "interview_id": record.interview_id,
        "candidate_name": record.candidate_name,
        "candidate_email": record.candidate_email,
        "role_id": record.role_id,
        "job_offer": record.job_offer,
        "scheduled_at": record.scheduled_at,
        "expires_at": record.expires_at,
        "status": record.status,
        "invitation_status": record.invitation_status,
        "invitation_sent_at": record.invitation_sent_at,
        "invitation_error": record.invitation_error,
        "invitation_attempts": record.invitation_attempts,
        "reviewer": record.reviewer,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _csv_safe(value: str) -> str:
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


@app.get("/admin/audit-events")
def list_admin_audit_events(
    search: str = "", event_type: str = "", limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    items, total = INTERVIEW_REPOSITORY.list_audit(
        search=search, event_type=event_type, limit=limit, offset=offset
    )
    return {"items": items, "total": total, "limit": max(1, min(limit, 200)), "offset": max(0, offset)}


@app.get("/admin/analytics/sync-history")
def list_analytics_sync_history(limit: int = 50) -> list[dict[str, Any]]:
    return INTERVIEW_REPOSITORY.list_sync_runs(limit)


def _corpus_document_to_item(record: CorpusDocumentRecord) -> CorpusDocumentItem:
    return CorpusDocumentItem(**record.__dict__)


@app.post("/analytics/snapshots", response_model=AnalyticsSnapshotDetailResponse)
def create_analytics_snapshot(
    request: CreateAnalyticsSnapshotRequest | None = None,
) -> AnalyticsSnapshotDetailResponse:
    create_request = request or CreateAnalyticsSnapshotRequest()
    record = save_gold_snapshot(
        label=create_request.label,
        policy_version=create_request.policy_version.strip() or DEFAULT_POLICY_VERSION,
        prompt_version=create_request.prompt_version.strip() or DEFAULT_PROMPT_VERSION,
        integrity_repository=INTERVIEW_REPOSITORY,
    )
    payload = _load_analytics_payload(record.payload_json, record.snapshot_id)
    return AnalyticsSnapshotDetailResponse(
        snapshot_id=record.snapshot_id,
        label=record.label,
        policy_version=record.policy_version,
        prompt_version=record.prompt_version,
        created_at=record.created_at,
        snapshot=payload,
        llm_trace_rollup=_load_optional_json_object(
            record.llm_trace_rollup_json,
            "snapshot llm_trace_rollup",
            record.snapshot_id,
        ),
    )


@app.get("/analytics/snapshots", response_model=list[AnalyticsSnapshotSummaryItem])
def list_analytics_snapshots(limit: int = 50) -> list[AnalyticsSnapshotSummaryItem]:
    records = PERSISTENCE.list_analytics_snapshots(limit=max(1, min(limit, 200)))
    response: list[AnalyticsSnapshotSummaryItem] = []
    for record in records:
        generated_at: str | None = None
        try:
            payload = _load_analytics_payload(record.payload_json, record.snapshot_id)
            generated_value = payload.get("generated_at")
            if isinstance(generated_value, str):
                generated_at = generated_value
        except HTTPException:
            generated_at = None

        response.append(
            AnalyticsSnapshotSummaryItem(
                snapshot_id=record.snapshot_id,
                label=record.label,
                policy_version=record.policy_version,
                prompt_version=record.prompt_version,
                created_at=record.created_at,
                generated_at=generated_at,
            )
        )

    return response


@app.get("/analytics/snapshots/{snapshot_id}", response_model=AnalyticsSnapshotDetailResponse)
def get_analytics_snapshot(snapshot_id: int) -> AnalyticsSnapshotDetailResponse:
    record = PERSISTENCE.load_analytics_snapshot(snapshot_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    payload = _load_analytics_payload(record.payload_json, record.snapshot_id)
    return AnalyticsSnapshotDetailResponse(
        snapshot_id=record.snapshot_id,
        label=record.label,
        policy_version=record.policy_version,
        prompt_version=record.prompt_version,
        created_at=record.created_at,
        snapshot=payload,
        llm_trace_rollup=_load_optional_json_object(
            record.llm_trace_rollup_json,
            "snapshot llm_trace_rollup",
            record.snapshot_id,
        ),
    )


@app.get("/analytics/compare", response_model=AnalyticsComparisonResponse)
def get_analytics_comparison(
    baseline_id: int,
    candidate_id: int,
) -> AnalyticsComparisonResponse:
    baseline = PERSISTENCE.load_analytics_snapshot(baseline_id)
    candidate = PERSISTENCE.load_analytics_snapshot(candidate_id)
    if baseline is None or candidate is None:
        raise HTTPException(status_code=404, detail="Baseline or candidate snapshot not found")

    comparison = compare_snapshot_ids(
        baseline_snapshot_id=baseline_id,
        candidate_snapshot_id=candidate_id,
    )
    return AnalyticsComparisonResponse(
        baseline_snapshot_id=baseline_id,
        candidate_snapshot_id=candidate_id,
        comparison=snapshot_to_dict(comparison),
    )


@app.post("/analytics/jobs/snapshot-sync", response_model=AnalyticsSnapshotSyncResponse)
def run_analytics_snapshot_sync(
    request: AnalyticsSnapshotSyncRequest | None = None,
) -> AnalyticsSnapshotSyncResponse:
    sync_request = request or AnalyticsSnapshotSyncRequest()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = run_snapshot_sync_job(
            label=sync_request.label,
            policy_version=sync_request.policy_version.strip() or DEFAULT_POLICY_VERSION,
            prompt_version=sync_request.prompt_version.strip() or DEFAULT_PROMPT_VERSION,
            integrity_repository=INTERVIEW_REPOSITORY,
        )
    except Exception as exc:
        completed_at = datetime.now(timezone.utc).isoformat()
        INTERVIEW_REPOSITORY.record_sync_run("failed", None, str(exc), started_at, completed_at)
        INTERVIEW_REPOSITORY.record_audit("analytics.snapshot_sync.failed", "analytics", {"error": str(exc)})
        raise HTTPException(status_code=500, detail="Analytics snapshot sync failed") from exc
    completed_at = datetime.now(timezone.utc).isoformat()
    INTERVIEW_REPOSITORY.record_sync_run(
        "completed", result.get("snapshot_id"), "Snapshot created", started_at, completed_at
    )
    INTERVIEW_REPOSITORY.record_audit(
        "analytics.snapshot_sync.completed", "analytics", {"snapshot_id": result.get("snapshot_id")}
    )
    return AnalyticsSnapshotSyncResponse(**result)


@app.post("/analytics/evaluations/drift-check", response_model=DriftCheckResponse)
def run_analytics_drift_check(request: DriftCheckRequest | None = None) -> DriftCheckResponse:
    drift_request = request or DriftCheckRequest()

    try:
        result = run_drift_check_job(
            baseline_snapshot_id=drift_request.baseline_snapshot_id,
            candidate_snapshot_id=drift_request.candidate_snapshot_id,
            score_drop_threshold=drift_request.score_drop_threshold,
            override_increase_threshold=drift_request.override_increase_threshold,
            fairness_score_delta_threshold=drift_request.fairness_score_delta_threshold,
            fairness_override_delta_threshold=drift_request.fairness_override_delta_threshold,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DriftCheckResponse(**result)


@app.get("/analytics/evaluations", response_model=list[AnalyticsEvaluationSummaryItem])
def list_analytics_evaluations(limit: int = 50) -> list[AnalyticsEvaluationSummaryItem]:
    records = PERSISTENCE.list_analytics_evaluations(limit=max(1, min(limit, 200)))
    return [
        AnalyticsEvaluationSummaryItem(
            evaluation_id=record.evaluation_id,
            evaluation_type=record.evaluation_type,
            status=record.status,
            baseline_snapshot_id=record.baseline_snapshot_id,
            candidate_snapshot_id=record.candidate_snapshot_id,
            created_at=record.created_at,
        )
        for record in records
    ]


@app.get(
    "/analytics/evaluations/trends",
    response_model=AnalyticsEvaluationTrendResponse,
)
def get_analytics_evaluation_trends(limit: int = 20) -> AnalyticsEvaluationTrendResponse:
    records = PERSISTENCE.list_analytics_evaluations(limit=max(1, min(limit, 200)))
    points: list[LlmFallbackTrendPoint] = []

    for record in reversed(records):
        rollup = _load_llm_trace_rollup_for_evaluation(record)
        if rollup is None:
            continue

        baseline = rollup.get("baseline")
        candidate = rollup.get("candidate")
        baseline_payload = baseline if isinstance(baseline, dict) else {}
        candidate_payload = candidate if isinstance(candidate, dict) else {}

        points.append(
            LlmFallbackTrendPoint(
                evaluation_id=record.evaluation_id,
                created_at=record.created_at,
                status=record.status,
                baseline_snapshot_id=record.baseline_snapshot_id,
                candidate_snapshot_id=record.candidate_snapshot_id,
                baseline_fallback_rate=_rollup_float(baseline_payload, "fallback_rate"),
                candidate_fallback_rate=_rollup_float(candidate_payload, "fallback_rate"),
                fallback_rate_delta=_rollup_float(rollup, "fallback_rate_delta"),
                observed_turn_count_delta=_rollup_int(rollup, "observed_turn_count_delta"),
            )
        )

    if not points:
        return AnalyticsEvaluationTrendResponse(
            evaluation_count=0,
            average_baseline_fallback_rate=0.0,
            average_candidate_fallback_rate=0.0,
            average_fallback_rate_delta=0.0,
            max_candidate_fallback_rate=0.0,
            points=[],
        )

    return AnalyticsEvaluationTrendResponse(
        evaluation_count=len(points),
        average_baseline_fallback_rate=(
            sum(point.baseline_fallback_rate for point in points) / len(points)
        ),
        average_candidate_fallback_rate=(
            sum(point.candidate_fallback_rate for point in points) / len(points)
        ),
        average_fallback_rate_delta=(
            sum(point.fallback_rate_delta for point in points) / len(points)
        ),
        max_candidate_fallback_rate=max(point.candidate_fallback_rate for point in points),
        points=points,
    )


@app.get(
    "/analytics/evaluations/{evaluation_id}",
    response_model=AnalyticsEvaluationDetailResponse,
)
def get_analytics_evaluation(evaluation_id: int) -> AnalyticsEvaluationDetailResponse:
    record = PERSISTENCE.load_analytics_evaluation(evaluation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    return AnalyticsEvaluationDetailResponse(
        evaluation_id=record.evaluation_id,
        evaluation_type=record.evaluation_type,
        status=record.status,
        baseline_snapshot_id=record.baseline_snapshot_id,
        candidate_snapshot_id=record.candidate_snapshot_id,
        thresholds=_load_json_object(record.thresholds_json, "thresholds", record.evaluation_id),
        result=_load_json_object(record.result_json, "result", record.evaluation_id),
        llm_trace_rollup=_load_optional_json_object(
            record.llm_trace_rollup_json,
            "evaluation llm_trace_rollup",
            record.evaluation_id,
        ),
        created_at=record.created_at,
    )


def _build_grounded_context(
    query_text: str, role: str, doc_type: str, competency: str | None = None
) -> list[GroundedContextItem]:
    results = RETRIEVAL_SERVICE.retrieve(
        query_text=query_text,
        role=role,
        doc_type=doc_type,
        top_k=2,
        competency=competency,
    )

    return [
        GroundedContextItem(
            chunk_id=item.chunk.chunk_id,
            doc_id=item.chunk.doc_id,
            doc_type=item.chunk.doc_type,
            role=item.chunk.role,
            text=item.chunk.text,
            score=item.score,
        )
        for item in results
    ]


def _build_citation_list(
    grounded_context: list[GroundedContextItem],
) -> list[CitationItem]:
    citations: list[CitationItem] = []
    seen: set[str] = set()

    for item in grounded_context:
        if item.chunk_id in seen:
            continue

        seen.add(item.chunk_id)
        citations.append(
            CitationItem(
                source_id=item.chunk_id,
                doc_id=item.doc_id,
                doc_type=item.doc_type,
                role=item.role,
            )
        )

    return citations


def _build_graph_state(snapshot) -> GraphStateItem:
    confidence_average = (
        snapshot.confidence_sum / snapshot.evaluated_turns if snapshot.evaluated_turns > 0 else 0.0
    )

    return GraphStateItem(
        current_competency=snapshot.current_competency,
        current_turn_index=snapshot.current_turn_index,
        max_turns=snapshot.max_turns,
        total_competencies=snapshot.total_competencies,
        remaining_competencies=snapshot.remaining_competencies,
        evaluated_turns=snapshot.evaluated_turns,
        confidence_sum=snapshot.confidence_sum,
        confidence_average=round(confidence_average, 4),
        off_topic_count=snapshot.off_topic_count,
        final_route=snapshot.final_route,
        decision_summary=snapshot.decision_summary,
        route_history=snapshot.route_history,
        decision_log_tail=[
            DecisionLogItem(
                node=item.node,
                route=item.route,
                reason=item.reason,
                alternatives=item.alternatives,
            )
            for item in snapshot.decision_log_tail
        ],
        llm_trace=snapshot.llm_trace,
    )


def _build_review_state(snapshot, completed: bool) -> ReviewStateItem:
    completed_competencies = max(0, snapshot.total_competencies - snapshot.remaining_competencies)
    competency_coverage = (
        completed_competencies / snapshot.total_competencies if snapshot.total_competencies > 0 else 0.0
    )
    confidence_average = (
        snapshot.confidence_sum / snapshot.evaluated_turns if snapshot.evaluated_turns > 0 else 0.0
    )
    competency_coverage_target = 1.0
    cumulative_confidence_target = 0.70

    return ReviewStateItem(
        active_competency=snapshot.current_competency,
        turn_index=snapshot.current_turn_index,
        completed=completed,
        decision_summary=snapshot.decision_summary,
        route_history=snapshot.route_history,
        decision_trail_count=len(snapshot.decision_log_tail),
        competency_coverage=round(competency_coverage, 4),
        competency_coverage_target=competency_coverage_target,
        competency_coverage_met=competency_coverage >= competency_coverage_target,
        cumulative_confidence=round(confidence_average, 4),
        cumulative_confidence_target=cumulative_confidence_target,
        cumulative_confidence_met=confidence_average >= cumulative_confidence_target,
        safety_turn_limit=snapshot.max_turns,
        safety_turn_limit_reached=snapshot.current_turn_index >= snapshot.max_turns,
        off_topic_count=snapshot.off_topic_count,
    )


def _build_integrity_state(
    request: IntegrityRequestItem | None,
    signal_deviations: dict[str, float] | None = None,
) -> IntegrityStateItem:
    integrity_request = request or IntegrityRequestItem()
    if not integrity_request.disclosure_accepted and integrity_request.telemetry_events:
        raise HTTPException(
            status_code=400,
            detail="Telemetry events require an accepted integrity disclosure",
        )
    integrity_config = INTERVIEW_REPOSITORY.get_setting("integrity") or {}
    declaration = AccommodationDeclaration(
        disclosure_accepted=integrity_request.disclosure_accepted,
        focus_telemetry_enabled=integrity_request.focus_telemetry_enabled,
        suppressed_signal_families=[
            cast(SignalFamily, item)
            for item in integrity_request.suppressed_signal_families
        ],
    )
    report = analyze_integrity(
        declaration=declaration,
        telemetry_events=[
            TelemetryEvent(
                signal_family=cast(SignalFamily, item.signal_family),
                event_type=item.event_type,
                value=item.value,
            )
            for item in integrity_request.telemetry_events
            if item.signal_family not in integrity_request.suppressed_signal_families
            and (item.signal_family != "focus" or integrity_request.focus_telemetry_enabled)
        ],
        signal_weights=integrity_config.get("signal_weights"),
        max_penalty=integrity_config.get("max_penalty", 100),
        ai_text_cap=integrity_config.get("ai_text_cap", 0.1),
        signal_deviations=signal_deviations,
    )
    return _integrity_report_to_item(report)


def _with_integrity_baseline(
    run_id: str, answer: str, request: IntegrityRequestItem | None
) -> IntegrityStateItem:
    baseline_length = None
    baseline_counts: dict[str, int] = {}
    baseline_metrics: dict[str, list[float]] = {}
    for event in PERSISTENCE.load_events(run_id):
        if event.event_type == "warmup_completed":
            candidate = event.payload.get("answer_length")
            baseline_disclosure = event.payload.get("integrity_state", {}).get(
                "disclosure_accepted", False
            )
            if isinstance(candidate, int) and baseline_disclosure:
                baseline_length = candidate
                baseline_metrics.setdefault("answer_length", []).append(float(candidate))
            raw_events = event.payload.get("telemetry_events", [])
            if isinstance(raw_events, list):
                for item in raw_events:
                    if not isinstance(item, dict):
                        continue
                    family = item.get("signal_family")
                    event_type = item.get("event_type")
                    value = item.get("value")
                    if isinstance(family, str):
                        baseline_counts[family] = baseline_counts.get(family, 0) + 1
                    if isinstance(event_type, str) and isinstance(value, str):
                        try:
                            baseline_metrics.setdefault(event_type, []).append(float(value))
                        except ValueError:
                            pass
                break
    if baseline_length is None:
        return _build_integrity_state(request)

    current_length = len(answer.strip())
    deviation = abs(current_length - baseline_length) / max(baseline_length, 1)
    current_metrics = dict(request.current_metrics) if request else {}
    if request and request.disclosure_accepted:
        current_metrics.setdefault("answer_length", float(current_length))
    metric_families = {
        "answer_length": "input",
        "time_to_first_keystroke_ms": "timing",
        "composition_time_ms": "timing",
        "words_per_minute": "timing",
        "keystroke_interval_ms": "input",
        "paste_fraction": "input",
        "revision_ratio": "input",
        "focus_blur_count": "focus",
    }
    suppressed = set(request.suppressed_signal_families if request else [])
    focus_enabled = request.focus_telemetry_enabled if request else False
    metric_deviations: dict[str, float] = {}
    signal_deviations: dict[str, float] = {}
    for metric, family in metric_families.items():
        current = current_metrics.get(metric)
        samples = baseline_metrics.get(metric, [])
        if (
            current is None
            or not samples
            or family in suppressed
            or (family == "focus" and not focus_enabled)
        ):
            continue
        baseline = median(samples)
        mad = median([abs(sample - baseline) for sample in samples])
        scale = 1.4826 * mad
        if scale <= 1e-9:
            scale = max(abs(baseline) * 0.25, 1.0)
        modified_z = 0.6745 * abs(float(current) - baseline) / scale
        anomaly = 2 / (1 + exp(-min(modified_z, 12))) - 1
        metric_deviations[metric] = round(anomaly, 4)
        signal_deviations[family] = max(signal_deviations.get(family, 0.0), anomaly)

    state = _build_integrity_state(request, signal_deviations)
    current_counts: dict[str, int] = {}
    for item in request.telemetry_events if request else []:
        current_counts[item.signal_family] = current_counts.get(item.signal_family, 0) + 1
    signal_ratios = {
        **metric_deviations,
        **{
            family: round(abs(current_counts.get(family, 0) - baseline) / max(baseline, 1), 4)
            for family, baseline in baseline_counts.items()
        },
    }
    return state.model_copy(update={
        "baseline_available": True,
        "baseline_answer_length": baseline_length,
        "current_answer_length": current_length,
        "baseline_deviation_ratio": round(deviation, 4),
        "baseline_signal_counts": baseline_counts,
        "current_signal_counts": current_counts,
        "signal_deviation_ratios": signal_ratios,
    })


def _integrity_report_to_item(report: IntegrityReport) -> IntegrityStateItem:
    return IntegrityStateItem(
        disclosure_accepted=report.disclosure_accepted,
        focus_telemetry_enabled=report.focus_telemetry_enabled,
        aai_index=report.aai_index,
        signal_breakdown=[
            IntegrityBreakdownItem(
                signal_family=item.signal_family,
                event_count=item.event_count,
                suppressed=item.suppressed,
                evidence=item.evidence,
            )
            for item in report.signal_breakdown
        ],
        confounders=report.confounders,
        disposition=report.disposition,
        suppressed_signal_families=cast(list[str], report.suppressed_signal_families),
    )


def _restore_run_context(run_id: str) -> RunContext | None:
    record = PERSISTENCE.load_run(run_id)
    if record is None:
        return None

    graph = InterviewGraph.restore(
        RuntimeStateRecord(
            role=record.role,
            doc_type=record.doc_type,
            state=json.loads(record.state_json),
        ),
        retrieval_service=RETRIEVAL_SERVICE,
    )
    warmup_pending = not any(
        event.event_type == "warmup_completed" for event in PERSISTENCE.load_events(run_id)
    )
    return RunContext(
        graph=graph,
        role=record.role,
        doc_type=record.doc_type,
        interview_id=INTERVIEW_REPOSITORY.get_interview_id_for_run(run_id),
        warmup_pending=warmup_pending,
    )


def _load_analytics_payload(payload_json: str, snapshot_id: int) -> dict[str, Any]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Snapshot {snapshot_id} has invalid JSON payload",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail=f"Snapshot {snapshot_id} payload must be an object",
        )

    return payload


def _load_json_object(payload_json: str, kind: str, row_id: int) -> dict[str, Any]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Analytics {kind} payload is invalid for row {row_id}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail=f"Analytics {kind} payload must be an object for row {row_id}",
        )

    return payload


def _load_optional_json_object(
    payload_json: str | None,
    kind: str,
    row_id: int,
) -> dict[str, Any] | None:
    if payload_json is None:
        return None
    return _load_json_object(payload_json, kind=kind, row_id=row_id)


def _load_llm_trace_rollup_for_evaluation(
    record,
) -> dict[str, Any] | None:
    if record.llm_trace_rollup_json is not None:
        return _load_json_object(
            record.llm_trace_rollup_json,
            kind="evaluation llm_trace_rollup",
            row_id=record.evaluation_id,
        )

    result = _load_json_object(record.result_json, kind="result", row_id=record.evaluation_id)
    rollup = result.get("llm_trace_rollup")
    return rollup if isinstance(rollup, dict) else None


def _rollup_float(payload: dict[str, Any], key: str) -> float:
    return float(payload.get(key, 0.0))


def _rollup_int(payload: dict[str, Any], key: str) -> int:
    return int(payload.get(key, 0))
