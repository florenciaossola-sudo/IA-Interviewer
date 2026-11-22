from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from services.agent.graph.evaluator import GroundingEvidenceRequired, evaluate_answer
from services.agent.graph.llm import (
    LlmAdapter,
    LlmAdapterError,
    build_llm_adapter_from_environment,
)
from services.agent.graph.models import (
    Competency,
    DecisionContext,
    DecisionLogEntry,
    DecisionRoute,
    InterviewGraphState,
    RetrievalEvidence,
)
from services.agent.graph.policy import decide_route
from services.agent.graph.questions import (
    MODEL_OVERLOADED_MESSAGE,
    QuestionGenerator,
    QuestionGeneratorError,
    build_question_generator_from_environment,
)
from services.agent.retrieval import GroundedRetrievalService


class GraphExecutionEngine(Protocol):
    name: str

    def current_question(self, state: InterviewGraphState) -> str:
        ...

    def run_turn(
        self,
        answer: str,
        state: InterviewGraphState,
        retrieval: GroundedRetrievalService,
    ) -> DecisionRoute:
        ...


class LegacyExecutionEngine:
    name = "legacy"

    def __init__(self, question_generator: QuestionGenerator | None = None) -> None:
        self._question_generator = question_generator or build_question_generator_from_environment()

    def current_question(self, state: InterviewGraphState) -> str:
        _trace_node("ask", state, status="start")
        try:
            question = self._question_generator.generate_question(state)
            _trace_node("ask", state, status="completed", question=question)
            return question
        except Exception as exc:
            try:
                import traceback

                print(f"[ERROR] Question generator failed: {exc}")
                traceback.print_exc()
            except Exception:
                pass
            _trace_node("ask", state, status="failed", error=str(exc))
            return MODEL_OVERLOADED_MESSAGE

    def run_turn(
        self,
        answer: str,
        state: InterviewGraphState,
        retrieval: GroundedRetrievalService,
    ) -> DecisionRoute:
        competency = state.current_competency

        _trace_node("plan", state, answer=answer, competency=competency)
        _plan_node(competency)
        _trace_node("retrieve", state, answer=answer)
        grounded_sources = _retrieve_node(retrieval, answer, competency, state)
        _trace_node("evaluate", state, answer=answer)
        evaluation = evaluate_answer(answer, competency, grounded_sources)
        state.last_evaluation_score = evaluation.score
        state.last_evaluation_evidence = evaluation.evidence
        state.last_evaluation_source_refs = _source_refs_to_dicts(evaluation.source_refs)
        _trace_node(
            "evaluate.completed",
            state,
            score=evaluation.score,
            off_topic=evaluation.off_topic,
            mixed_signal=evaluation.mixed_signal,
        )

        if evaluation.off_topic:
            state.off_topic_count += 1

        state.apply_answer_feedback(evaluation.score, evaluation.off_topic)

        route = decide_route(
            DecisionContext(
                turn_index=state.turn_index,
                max_turns=state.max_turns,
                score=evaluation.score,
                cumulative_score_before_turn=state.confidence_sum,
                evaluated_turns_before_turn=state.evaluated_turns,
                off_topic_count=state.off_topic_count,
                mixed_signal=evaluation.mixed_signal,
                remaining_competencies=state.remaining_competencies,
                decision_threshold=state.decision_threshold,
                conclusion_threshold=state.conclusion_threshold,
                confidence_threshold=state.confidence_threshold,
            )
        )
        _trace_node("decide", state, route=route, score=evaluation.score)

        _apply_route(
            state=state,
            route=route,
            evaluation=evaluation,
            llm_trace={
                "provider": "deterministic",
                "model": "local-evaluator",
                "fallback_used": False,
                "engine": self.name,
            },
        )
        _trace_node("finalize", state, route=route)
        return route


@dataclass
class _LangGraphTurnContext:
    answer: str
    competency: Competency
    role: str
    doc_type: str
    evaluation_score: float = 0.0
    evaluation_off_topic: bool = False
    evaluation_mixed_signal: bool = False
    grounded_sources: list[RetrievalEvidence] = field(default_factory=list)
    llm_trace: dict[str, object] | None = None
    route: DecisionRoute = "probe_deeper"


class LangGraphExecutionEngine:
    name = "langgraph"

    def __init__(
        self,
        llm_adapter: LlmAdapter | None = None,
        question_generator: QuestionGenerator | None = None,
    ) -> None:
        self._llm_adapter = llm_adapter or build_llm_adapter_from_environment()
        self._question_generator = question_generator or build_question_generator_from_environment()

    def current_question(self, state: InterviewGraphState) -> str:
        _trace_node("ask", state, status="start")
        try:
            question = self._question_generator.generate_question(state)
            _trace_node("ask", state, status="completed", question=question)
            return question
        except QuestionGeneratorError as exc:
            _trace_node("ask", state, status="failed", error=str(exc))
            return MODEL_OVERLOADED_MESSAGE

    def run_turn(
        self,
        answer: str,
        state: InterviewGraphState,
        retrieval: GroundedRetrievalService,
    ) -> DecisionRoute:
        context = _LangGraphTurnContext(
            answer=answer,
            competency=state.current_competency,
            role=state.role,
            doc_type=state.doc_type,
        )
        _trace_node("turn.start", state, answer=answer, competency=context.competency)
        self._node_plan(context=context)
        self._node_retrieve(context=context, retrieval=retrieval, state=state)
        self._node_evaluate(context=context, state=state)
        self._node_decide(context=context, state=state)
        self._node_finalize(context=context, state=state)
        return context.route

    def _node_plan(self, context: _LangGraphTurnContext) -> None:
        print(f"[TRACE] node=plan status=start competency={context.competency}", flush=True)
        _plan_node(context.competency)
        print(f"[TRACE] node=plan status=completed competency={context.competency}", flush=True)

    def _node_retrieve(
        self,
        context: _LangGraphTurnContext,
        retrieval: GroundedRetrievalService,
        state: InterviewGraphState,
    ) -> None:
        print(f"[TRACE] node=retrieve status=start competency={context.competency}", flush=True)
        context.grounded_sources = _retrieve_node(
            retrieval, context.answer, context.competency, state
        )
        print(f"[TRACE] node=retrieve status=completed competency={context.competency}", flush=True)

    def _node_ask(self, context: _LangGraphTurnContext, state: InterviewGraphState) -> None:
        self.current_question(state)

    def _node_evaluate(self, context: _LangGraphTurnContext, state: InterviewGraphState) -> None:
        print(f"[TRACE] node=evaluate status=start competency={context.competency}", flush=True)
        if not context.grounded_sources:
            raise GroundingEvidenceRequired(
                "Cannot score an answer without retrieved corpus evidence"
            )
        if self._llm_adapter is None:
            evaluation = evaluate_answer(
                context.answer, context.competency, context.grounded_sources
            )
            context.evaluation_score = evaluation.score
            state.last_evaluation_score = evaluation.score
            state.last_evaluation_evidence = evaluation.evidence
            state.last_evaluation_source_refs = _source_refs_to_dicts(evaluation.source_refs)
            context.evaluation_off_topic = evaluation.off_topic
            context.evaluation_mixed_signal = evaluation.mixed_signal
            context.llm_trace = {
                "provider": "deterministic",
                "model": "local-evaluator",
                "fallback_used": False,
                "engine": self.name,
            }
            print(
                f"[TRACE] node=evaluate status=completed provider=deterministic score={context.evaluation_score} "
                f"off_topic={context.evaluation_off_topic} mixed_signal={context.evaluation_mixed_signal}",
                flush=True,
            )
            return

        try:
            assessment = self._llm_adapter.assess_turn(
                answer=context.answer,
                competency=context.competency,
                role=context.role,
                doc_type=context.doc_type,
                grounded_sources=context.grounded_sources,
            )
            context.evaluation_score = assessment.score
            state.last_evaluation_score = assessment.score
            state.last_evaluation_evidence = assessment.evidence
            state.last_evaluation_source_refs = _source_refs_to_dicts(context.grounded_sources)
            context.evaluation_off_topic = assessment.off_topic
            context.evaluation_mixed_signal = assessment.mixed_signal
            context.llm_trace = {
                "provider": assessment.provider,
                "model": assessment.model,
                "fallback_used": False,
                "engine": self.name,
            }
            print(
                f"[TRACE] node=evaluate status=completed provider={assessment.provider} model={assessment.model} "
                f"score={context.evaluation_score} off_topic={context.evaluation_off_topic} "
                f"mixed_signal={context.evaluation_mixed_signal}",
                flush=True,
            )
        except LlmAdapterError:
            # Deterministic fallback protects behavior when provider output is invalid/unavailable.
            evaluation = evaluate_answer(
                context.answer, context.competency, context.grounded_sources
            )
            context.evaluation_score = evaluation.score
            state.last_evaluation_score = evaluation.score
            state.last_evaluation_evidence = evaluation.evidence
            state.last_evaluation_source_refs = _source_refs_to_dicts(evaluation.source_refs)
            context.evaluation_off_topic = evaluation.off_topic
            context.evaluation_mixed_signal = evaluation.mixed_signal
            context.llm_trace = {
                "provider": "deterministic",
                "model": "local-evaluator",
                "fallback_used": True,
                "engine": self.name,
            }
            print(
                f"[TRACE] node=evaluate status=fallback provider=deterministic score={context.evaluation_score} "
                f"off_topic={context.evaluation_off_topic} mixed_signal={context.evaluation_mixed_signal}",
                flush=True,
            )

    def _node_decide(self, context: _LangGraphTurnContext, state: InterviewGraphState) -> None:
        if context.evaluation_off_topic:
            state.off_topic_count += 1

        state.apply_answer_feedback(context.evaluation_score, context.evaluation_off_topic)

        context.route = decide_route(
            DecisionContext(
                turn_index=state.turn_index,
                max_turns=state.max_turns,
                score=context.evaluation_score,
                cumulative_score_before_turn=state.confidence_sum,
                evaluated_turns_before_turn=state.evaluated_turns,
                off_topic_count=state.off_topic_count,
                mixed_signal=context.evaluation_mixed_signal,
                remaining_competencies=state.remaining_competencies,
                decision_threshold=state.decision_threshold,
                conclusion_threshold=state.conclusion_threshold,
                confidence_threshold=state.confidence_threshold,
            )
        )
        print(
            f"[TRACE] node=decide status=completed route={context.route} score={context.evaluation_score} "
            f"turn_index={state.turn_index} difficulty={state.difficulty_label}",
            flush=True,
        )

    def _node_finalize(self, context: _LangGraphTurnContext, state: InterviewGraphState) -> None:
        _apply_route(
            state=state,
            route=context.route,
            evaluation_score=context.evaluation_score,
            evaluation_off_topic=context.evaluation_off_topic,
            evaluation_mixed_signal=context.evaluation_mixed_signal,
            llm_trace=context.llm_trace,
        )
        _trace_node("finalize", state, route=context.route)


def create_execution_engine(engine_name: str) -> GraphExecutionEngine:
    selected = engine_name.strip().lower()
    if selected == "langgraph":
        return LangGraphExecutionEngine()

    return LegacyExecutionEngine()


def _plan_node(competency: Competency) -> str:
    return f"Plan next turn for competency: {competency}"


def _retrieve_node(
    retrieval: GroundedRetrievalService,
    answer: str,
    competency: Competency,
    state: InterviewGraphState,
) -> list[RetrievalEvidence]:
    query_text = f"{competency} {answer}".strip()
    results = retrieval.retrieve(
        query_text=query_text,
        role=state.role,
        doc_type=state.doc_type,
        top_k=2,
        competency=competency,
    )

    return [
        RetrievalEvidence(
            source_id=result.chunk.chunk_id,
            doc_id=result.chunk.doc_id,
            text=result.chunk.text,
            score=result.score,
        )
        for result in results
    ]


def _source_refs_to_dicts(sources: list[RetrievalEvidence]) -> list[dict[str, object]]:
    return [
        {
            "source_id": source.source_id,
            "doc_id": source.doc_id,
            "score": source.score,
        }
        for source in sources
    ]


def _apply_route(
    state: InterviewGraphState,
    route: DecisionRoute,
    evaluation: Any | None = None,
    evaluation_score: float | None = None,
    evaluation_off_topic: bool | None = None,
    evaluation_mixed_signal: bool | None = None,
    llm_trace: dict[str, object] | None = None,
) -> None:
    if evaluation is not None:
        score = evaluation.score
        off_topic = evaluation.off_topic
        mixed_signal = evaluation.mixed_signal
    else:
        score = float(evaluation_score or 0.0)
        off_topic = bool(evaluation_off_topic)
        mixed_signal = bool(evaluation_mixed_signal)

    reason = f"score={score:.2f}; " f"off_topic={off_topic}; mixed={mixed_signal}"
    alternatives = [
        candidate
        for candidate in ("probe_deeper", "switch_competency", "conclude", "escalate")
        if candidate != route
    ]
    state.decision_log.append(
        DecisionLogEntry(node="decide", route=route, reason=reason, alternatives=alternatives)
    )
    state.confidence_sum += score
    state.evaluated_turns += 1
    state.llm_trace = llm_trace

    if route == "switch_competency" and state.remaining_competencies > 0:
        state.current_competency_index += 1

    if route in {"conclude", "escalate"}:
        state.final_route = route
        state.decision_log.append(
            DecisionLogEntry(node="human_review", route=route, reason="handoff to reviewer gate")
        )

    state.turn_index += 1


def _trace_node(node: str, state: InterviewGraphState, **details: object) -> None:
    state_data = {
        "turn_index": state.turn_index,
        "competency": state.current_competency,
        "difficulty": state.difficulty_label,
        "evaluated_turns": state.evaluated_turns,
        "off_topic_count": state.off_topic_count,
        "final_route": state.final_route,
    }
    print(f"[TRACE] node={node} state={state_data} details={details}", flush=True)
