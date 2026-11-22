from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict, TypeVar, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from services.agent.graph.engine import _apply_route
from services.agent.graph.evaluator import evaluate_answer
from services.agent.graph.llm import (
    LlmAdapterError,
    build_llm_adapter_from_environment,
)
from services.agent.graph.models import (
    Competency,
    DecisionContext,
    InterviewGraphState,
    RetrievalEvidence,
    TurnEvaluation,
)
from services.agent.graph.policy import decide_route
from services.agent.graph.questions import (
    MODEL_OVERLOADED_MESSAGE,
    QuestionGeneratorError,
    build_question_generator_from_environment,
)
from services.agent.retrieval import GroundedRetrievalService


class StudioInterviewState(TypedDict, total=False):
    role: str
    doc_type: str
    role_description: str
    answer: str
    question: str | None
    competency_order: list[Competency]
    current_competency_index: int
    current_competency: str
    turn_index: int
    max_turns: int
    decision_threshold: float
    recommendation_low_max: float
    recommendation_high_min: float
    conclusion_threshold: float
    confidence_threshold: float
    difficulty_level: int
    difficulty: str
    off_topic_count: int
    confidence_sum: float
    evaluated_turns: int
    last_evaluation_score: float | None
    last_evaluation_evidence: list[str]
    last_evaluation_source_refs: list[dict[str, object]]
    decision_log: list[dict[str, object]]
    remaining_competencies: int
    score: float
    off_topic: bool
    mixed_signal: bool
    evidence: list[str]
    route: str | None
    completed: bool
    fallback_used: bool
    provider: str | None
    model: str | None
    llm_trace: dict[str, object] | None
    grounded_context: list[dict[str, object]]
    review_decision: str
    review_rationale: str
    override_outcome: str | None
    report: dict[str, object]
    trace: list[dict[str, object]]
    last_node: str
    last_status: str


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "corpus.json"
RETRIEVAL = GroundedRetrievalService.from_environment(FIXTURE_PATH)
logger = logging.getLogger(__name__)


def set_retrieval_service(service: GroundedRetrievalService) -> None:
    global RETRIEVAL
    RETRIEVAL = service


def _runtime_state(state: StudioInterviewState) -> InterviewGraphState:
    raw_state: dict[str, object] = {
        "role": state.get("role", "backend_engineer"),
        "doc_type": state.get("doc_type", "role_description"),
        "role_description": state.get("role_description", ""),
        "competency_order": state.get(
            "competency_order", ["debugging", "api_design", "test_reliability"]
        ),
        "current_competency_index": state.get("current_competency_index", 0),
        "turn_index": state.get("turn_index", 0),
        "max_turns": state.get("max_turns", 5),
        "decision_threshold": state.get("decision_threshold", 0.75),
        "recommendation_low_max": state.get("recommendation_low_max", 0.40),
        "recommendation_high_min": state.get("recommendation_high_min", 0.70),
        "conclusion_threshold": state.get("conclusion_threshold", 0.55),
        "confidence_threshold": state.get("confidence_threshold", 0.70),
        "difficulty_level": state.get("difficulty_level", 2),
        "off_topic_count": state.get("off_topic_count", 0),
        "confidence_sum": state.get("confidence_sum", 0.0),
        "evaluated_turns": state.get("evaluated_turns", 0),
        "last_evaluation_score": state.get("last_evaluation_score"),
        "last_evaluation_evidence": state.get("last_evaluation_evidence", []),
        "last_evaluation_source_refs": state.get("last_evaluation_source_refs", []),
        "llm_trace": state.get("llm_trace"),
        "decision_log": state.get("decision_log", []),
        "pending_question": state.get("question"),
        "final_route": state.get("route"),
    }
    return InterviewGraphState.from_dict(raw_state)


def _state_update(runtime: InterviewGraphState) -> dict[str, object]:
    return {
        **runtime.to_dict(),
        "current_competency": runtime.current_competency,
        "difficulty": runtime.difficulty_label,
        "remaining_competencies": runtime.remaining_competencies,
    }


def _event(
    state: StudioInterviewState,
    node: str,
    status: str,
    **details: object,
) -> dict[str, object]:
    event = {
        "sequence": len(state.get("trace", [])) + 1,
        "node": node,
        "status": status,
        "details": details,
    }
    return {
        "trace": [*state.get("trace", []), event],
        "last_node": node,
        "last_status": status,
    }


_TRACE_SKIP_KEYS = {"trace", "decision_log", "competency_order", "llm_trace"}
_NodeFn = TypeVar("_NodeFn", bound=Callable[..., dict[str, object]])


def _trace_enabled() -> bool:
    return os.getenv("AI_INTERVIEWER_TRACE_NODES", "1").strip().lower() in {"1", "true", "yes", "on"}


def _compact(value: object, limit: int = 400) -> object:
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}... [{len(value)} chars]"
    if isinstance(value, dict):
        return {key: _compact(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact(item, limit) for item in value[:5]] + (
            [f"... +{len(value) - 5} more"] if len(value) > 5 else []
        )
    return value


def _trace_print(label: str, payload: object) -> None:
    print(f"[GRAPH] {label} {json.dumps(_compact(payload), ensure_ascii=False, default=str)}", flush=True)


def _traced(
    name: str, node: _NodeFn
) -> _NodeFn:
    def wrapper(state: StudioInterviewState) -> dict[str, object]:
        if not _trace_enabled():
            return node(state)
        visible = {key: value for key, value in state.items() if key not in _TRACE_SKIP_KEYS}
        _trace_print(f"node={name} INPUT", visible)
        started = time.perf_counter()
        try:
            result = node(state)
        except Exception as exc:
            elapsed = round((time.perf_counter() - started) * 1000)
            _trace_print(f"node={name} STOP ({type(exc).__name__}) in {elapsed}ms", {})
            raise
        elapsed = round((time.perf_counter() - started) * 1000)
        output = {key: value for key, value in result.items() if key not in _TRACE_SKIP_KEYS}
        _trace_print(f"node={name} OUTPUT in {elapsed}ms", output)
        return result

    return cast(_NodeFn, wrapper)


def entry_router(state: StudioInterviewState) -> str:
    if state.get("completed"):
        target = "report"
    elif not state.get("question"):
        target = "generate_question"
    elif state.get("answer", "").strip():
        target = "plan"
    else:
        target = "await_candidate"
    if _trace_enabled():
        _trace_print(
            "edge=entry_router",
            {
                "to": target,
                "has_question": bool(state.get("question")),
                "has_answer": bool(state.get("answer", "").strip()),
                "completed": bool(state.get("completed")),
            },
        )
    return target


def plan_node(state: StudioInterviewState) -> dict[str, object]:
    runtime = _runtime_state(state)
    return {
        **_event(state, "plan", "completed", competency=runtime.current_competency),
        **_state_update(runtime),
    }


def retrieve_node(state: StudioInterviewState) -> dict[str, object]:
    runtime = _runtime_state(state)
    answer = state.get("answer", "")
    results = RETRIEVAL.retrieve(
        query_text=f"{runtime.current_competency} {answer}".strip(),
        role=runtime.role,
        doc_type=runtime.doc_type,
        top_k=2,
        competency=runtime.current_competency,
    )
    grounded_context = [
        {
            "source_id": result.chunk.chunk_id,
            "doc_id": result.chunk.doc_id,
            "text": result.chunk.text,
            "score": result.score,
        }
        for result in results
    ]
    return {
        **_event(state, "retrieve", "completed", result_count=len(grounded_context)),
        "grounded_context": grounded_context,
    }


def evaluate_node(state: StudioInterviewState) -> dict[str, object]:
    runtime = _runtime_state(state)
    answer = state.get("answer", "")
    grounded_sources = [_retrieval_evidence(item) for item in state.get("grounded_context", [])]
    adapter = build_llm_adapter_from_environment()
    fallback_used = False
    fallback_error: str | None = None
    provider: str | None = None
    model: str | None = None

    if adapter is None:
        evaluation = evaluate_answer(answer, runtime.current_competency, grounded_sources)
        provider = "deterministic"
        model = "local-evaluator"
    else:
        try:
            for attempt in range(2):
                try:
                    assessment = adapter.assess_turn(
                        answer=answer,
                        competency=runtime.current_competency,
                        role=runtime.role,
                        doc_type=runtime.doc_type,
                        grounded_sources=grounded_sources,
                    )
                    break
                except LlmAdapterError:
                    if attempt == 1:
                        raise
                    time.sleep(2)
            evaluation = TurnEvaluation(
                score=assessment.score,
                off_topic=assessment.off_topic,
                mixed_signal=assessment.mixed_signal,
                evidence=assessment.evidence,
                source_refs=grounded_sources,
            )
            provider = assessment.provider
            model = assessment.model
        except LlmAdapterError as exc:
            logger.warning("LLM evaluation failed, using deterministic evaluator: %s", exc)
            fallback_error = str(exc)[:300]
            evaluation = evaluate_answer(answer, runtime.current_competency, grounded_sources)
            fallback_used = True
            provider = "deterministic"
            model = "local-evaluator"

    runtime.last_evaluation_score = evaluation.score
    runtime.last_evaluation_evidence = evaluation.evidence
    runtime.last_evaluation_source_refs = [
        {"source_id": source.source_id, "doc_id": source.doc_id, "score": source.score}
        for source in evaluation.source_refs
    ]

    return {
        **_event(
            state,
            "evaluate",
            "completed" if not fallback_used else "fallback",
            provider=provider,
            model=model,
            error=fallback_error,
            score=evaluation.score,
            off_topic=evaluation.off_topic,
            mixed_signal=evaluation.mixed_signal,
        ),
        "score": evaluation.score,
        "off_topic": evaluation.off_topic,
        "mixed_signal": evaluation.mixed_signal,
        "evidence": evaluation.evidence,
        "last_evaluation_score": runtime.last_evaluation_score,
        "last_evaluation_evidence": runtime.last_evaluation_evidence,
        "last_evaluation_source_refs": runtime.last_evaluation_source_refs,
        "fallback_used": fallback_used,
        "provider": provider,
        "model": model,
    }


def _retrieval_evidence(item: dict[str, object]) -> RetrievalEvidence:
    raw_score = item.get("score")
    score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
    return RetrievalEvidence(
        source_id=str(item.get("source_id", "")),
        doc_id=str(item.get("doc_id", "")),
        text=str(item.get("text", "")),
        score=score,
    )


def decide_node(state: StudioInterviewState) -> dict[str, object]:
    runtime = _runtime_state(state)
    score = float(state.get("score", 0.0))
    off_topic = bool(state.get("off_topic", False))
    mixed_signal = bool(state.get("mixed_signal", False))

    if off_topic:
        runtime.off_topic_count += 1
    runtime.apply_answer_feedback(score, off_topic)
    route = decide_route(
        DecisionContext(
            turn_index=runtime.turn_index,
            max_turns=runtime.max_turns,
            score=score,
            cumulative_score_before_turn=runtime.confidence_sum,
            evaluated_turns_before_turn=runtime.evaluated_turns,
            off_topic_count=runtime.off_topic_count,
            mixed_signal=mixed_signal,
            remaining_competencies=runtime.remaining_competencies,
        )
    )
    _apply_route(
        state=runtime,
        route=route,
        evaluation_score=score,
        evaluation_off_topic=off_topic,
        evaluation_mixed_signal=mixed_signal,
        llm_trace={
            "provider": state.get("provider"),
            "model": state.get("model"),
            "fallback_used": state.get("fallback_used", False),
            "engine": "studio",
        },
    )
    return {
        **_event(
            state,
            "decide",
            "completed",
            route=route,
            score=score,
            difficulty=runtime.difficulty_label,
        ),
        **_state_update(runtime),
        "route": route,
        "answer": "",
    }


def generate_question_node(state: StudioInterviewState) -> dict[str, object]:
    runtime = _runtime_state(state)
    try:
        question = build_question_generator_from_environment().generate_question(runtime)
        status = "completed"
    except QuestionGeneratorError:
        question = MODEL_OVERLOADED_MESSAGE
        status = "failed"
    return {
        **_event(
            state,
            "generate_question",
            status,
            competency=runtime.current_competency,
            difficulty=runtime.difficulty_label,
        ),
        **_state_update(runtime),
        "question": question,
        "completed": False,
    }


def await_candidate_node(state: StudioInterviewState) -> dict[str, object]:
    answer = interrupt(
        {
            "kind": "candidate_answer",
            "question": state.get("question"),
            "turn_index": state.get("turn_index", 0),
        }
    )
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Candidate answer must be non-empty")
    return {
        **_event(state, "await_candidate", "resumed"),
        "answer": answer,
    }


def human_review_node(state: StudioInterviewState) -> dict[str, object]:
    review = interrupt(
        {
            "kind": "human_review",
            "route": state.get("route"),
            "decision_options": ["approved", "overridden"],
        }
    )
    if not isinstance(review, dict):
        raise ValueError("Reviewer response must be an object")
    decision = review.get("decision")
    rationale = review.get("rationale")
    override_outcome = review.get("override_outcome")
    if decision not in {"approved", "overridden"}:
        raise ValueError("Reviewer decision must be approved or overridden")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Reviewer rationale is required")
    if decision == "overridden" and override_outcome not in {"conclude", "escalate"}:
        raise ValueError("Reviewer override must be conclude or escalate")
    if decision == "approved" and override_outcome is not None:
        raise ValueError("Approved reviews cannot include an override")
    return {
        **_event(state, "human_review", "completed", decision=decision),
        "review_decision": decision,
        "review_rationale": rationale.strip(),
        "override_outcome": override_outcome,
    }


def report_node(state: StudioInterviewState) -> dict[str, object]:
    if not state.get("review_decision") or not state.get("review_rationale"):
        raise ValueError("A human review is required before reporting")
    return {
        **_event(state, "report", "completed", route=state.get("route")),
        "completed": True,
        "question": None,
        "report": {
            "route": state.get("override_outcome") or state.get("route"),
            "review_decision": state.get("review_decision"),
            "review_rationale": state.get("review_rationale"),
        },
    }


builder = StateGraph(StudioInterviewState)
builder.add_node("plan", _traced("plan", plan_node))
builder.add_node("retrieve", _traced("retrieve", retrieve_node))
builder.add_node("evaluate", _traced("evaluate", evaluate_node))
builder.add_node("decide", _traced("decide", decide_node))
builder.add_node("generate_question", _traced("generate_question", generate_question_node))
builder.add_node("await_candidate", _traced("await_candidate", await_candidate_node))
builder.add_node("human_review", _traced("human_review", human_review_node))
builder.add_node("report", _traced("report", report_node))

builder.add_conditional_edges(
    START,
    entry_router,
    {
        "plan": "plan",
        "generate_question": "generate_question",
        "report": "report",
        "await_candidate": "await_candidate",
    },
)
builder.add_edge("plan", "retrieve")
builder.add_edge("retrieve", "evaluate")
builder.add_edge("evaluate", "decide")
builder.add_edge("generate_question", "await_candidate")
builder.add_edge("await_candidate", "plan")
builder.add_conditional_edges(
    "decide",
    lambda state: "review" if state.get("route") in {"conclude", "escalate"} else "continue",
    {"continue": "generate_question", "review": "human_review"},
)
builder.add_edge("human_review", "report")
builder.add_edge("report", END)

graph = builder.compile()
