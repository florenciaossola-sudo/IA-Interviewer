from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from services.agent.graph.engine import create_execution_engine
from services.agent.graph.models import (
    DecisionLogEntry,
    DecisionRoute,
    InterviewGraphState,
)
from services.agent.retrieval import GroundedRetrievalService


@dataclass(frozen=True)
class ReplayResult:
    final_route: DecisionRoute
    route_sequence: list[DecisionRoute]
    decision_log: list[DecisionLogEntry]


@dataclass(frozen=True)
class TurnStepResult:
    route: DecisionRoute
    completed: bool
    question: str | None
    question_index: int
    total_questions: int


@dataclass(frozen=True)
class GraphSnapshot:
    current_competency: str
    current_turn_index: int
    max_turns: int
    total_competencies: int
    remaining_competencies: int
    confidence_sum: float
    evaluated_turns: int
    off_topic_count: int
    final_route: DecisionRoute | None
    decision_summary: str
    route_history: list[DecisionRoute]
    decision_log_tail: list[DecisionLogEntry]
    llm_trace: dict[str, object] | None


@dataclass(frozen=True)
class RuntimeStateRecord:
    role: str
    doc_type: str
    state: dict[str, object]


class InterviewGraph:
    def __init__(
        self,
        role: str,
        doc_type: str,
        state: InterviewGraphState | None = None,
        retrieval_service: GroundedRetrievalService | None = None,
    ) -> None:
        fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "corpus.json"
        self._retrieval = retrieval_service or GroundedRetrievalService.from_environment(
            fixture_path
        )
        self._state = state or InterviewGraphState(role=role, doc_type=doc_type)
        configured_engine = os.getenv("AI_INTERVIEWER_AGENT_ENGINE", "legacy")
        self._engine = create_execution_engine(configured_engine)

    @classmethod
    def restore(
        cls,
        record: RuntimeStateRecord,
        retrieval_service: GroundedRetrievalService | None = None,
    ) -> InterviewGraph:
        return cls(
            role=record.role,
            doc_type=record.doc_type,
            state=InterviewGraphState.from_dict(record.state),
            retrieval_service=retrieval_service,
        )

    def replay_answers(self, answers: list[str]) -> ReplayResult:
        route_sequence: list[DecisionRoute] = []

        for answer in answers:
            if self._state.final_route in {"conclude", "escalate"}:
                break

            route = self._run_turn(answer)
            route_sequence.append(route)

        final_route = self._state.final_route or "escalate"
        return ReplayResult(
            final_route=final_route,
            route_sequence=route_sequence,
            decision_log=self._state.decision_log,
        )

    def set_filters(self, role: str, doc_type: str) -> None:
        self._state.role = role
        self._state.doc_type = doc_type

    def current_question(self) -> str:
        if self._state.pending_question:
            return self._state.pending_question

        question = self._engine.current_question(self._state)
        self._state.pending_question = question
        return question

    def total_questions(self) -> int:
        return self._state.max_turns

    def export_state(self) -> RuntimeStateRecord:
        return RuntimeStateRecord(
            role=self._state.role,
            doc_type=self._state.doc_type,
            state=self._state.to_dict(),
        )

    def snapshot(self, tail_size: int = 3) -> GraphSnapshot:
        route_history = [item.route for item in self._state.decision_log if item.node == "decide"]
        summary_route = self._state.final_route or (route_history[-1] if route_history else None)
        decision_summary = (
            f"competency={self._state.current_competency}; "
            f"turn={self._state.turn_index}; route={summary_route or 'pending'}; "
            f"decisions={len(route_history)}"
        )

        return GraphSnapshot(
            current_competency=self._state.current_competency,
            current_turn_index=self._state.turn_index,
            max_turns=self._state.max_turns,
            total_competencies=len(self._state.competency_order),
            remaining_competencies=self._state.remaining_competencies,
            confidence_sum=self._state.confidence_sum,
            evaluated_turns=self._state.evaluated_turns,
            off_topic_count=self._state.off_topic_count,
            final_route=self._state.final_route,
            decision_summary=decision_summary,
            route_history=route_history,
            decision_log_tail=self._state.decision_log[-tail_size:],
            llm_trace=self._state.llm_trace,
        )

    def submit_answer(self, answer: str) -> TurnStepResult:
        if self._state.final_route in {"conclude", "escalate"}:
            return TurnStepResult(
                route=self._state.final_route,
                completed=True,
                question=None,
                question_index=min(self._state.turn_index, self._state.max_turns),
                total_questions=self._state.max_turns,
            )

        # Invalidate cached prompt: the next turn must ask a new question.
        self._state.pending_question = None
        route = self._run_turn(answer)

        completed = self._state.final_route in {"conclude", "escalate"}
        if completed:
            return TurnStepResult(
                route=route,
                completed=True,
                question=None,
                question_index=min(self._state.turn_index, self._state.max_turns),
                total_questions=self._state.max_turns,
            )

        return TurnStepResult(
            route=route,
            completed=False,
            question=self.current_question(),
            question_index=self._state.turn_index + 1,
            total_questions=self._state.max_turns,
        )

    def _run_turn(self, answer: str) -> DecisionRoute:
        return self._engine.run_turn(answer=answer, state=self._state, retrieval=self._retrieval)
