from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

NodeName = Literal[
    "plan",
    "retrieve",
    "ask",
    "evaluate",
    "decide",
    "human_review",
    "report",
]

DecisionRoute = Literal[
    "probe_deeper",
    "switch_competency",
    "conclude",
    "escalate",
]

Competency = Literal["debugging", "api_design", "test_reliability"]


@dataclass(frozen=True)
class RetrievalEvidence:
    source_id: str
    doc_id: str
    text: str
    score: float


@dataclass(frozen=True)
class TurnEvaluation:
    score: float
    off_topic: bool
    mixed_signal: bool
    evidence: list[str]
    source_refs: list[RetrievalEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionContext:
    turn_index: int
    max_turns: int
    score: float
    cumulative_score_before_turn: float
    evaluated_turns_before_turn: int
    off_topic_count: int
    mixed_signal: bool
    remaining_competencies: int
    decision_threshold: float = 0.75
    conclusion_threshold: float = 0.55
    confidence_threshold: float = 0.70


@dataclass(frozen=True)
class DecisionLogEntry:
    node: NodeName
    route: DecisionRoute
    reason: str
    alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "node": self.node,
            "route": self.route,
            "reason": self.reason,
            "alternatives": list(self.alternatives),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> DecisionLogEntry:
        return cls(
            node=cast(NodeName, data["node"]),
            route=cast(DecisionRoute, data["route"]),
            reason=cast(str, data["reason"]),
            alternatives=cast(list[str], data.get("alternatives", [])),
        )


@dataclass
class InterviewGraphState:
    role: str
    doc_type: str
    role_description: str = ""
    decision_threshold: float = 0.75
    recommendation_low_max: float = 0.40
    recommendation_high_min: float = 0.70
    conclusion_threshold: float = 0.55
    confidence_threshold: float = 0.70
    current_competency_index: int = 0
    competency_order: list[Competency] = field(
        default_factory=lambda: ["debugging", "api_design", "test_reliability"]
    )
    turn_index: int = 0
    max_turns: int = 5
    difficulty_level: int = 2
    off_topic_count: int = 0
    confidence_sum: float = 0.0
    evaluated_turns: int = 0
    last_evaluation_score: float | None = None
    last_evaluation_evidence: list[str] = field(default_factory=list)
    last_evaluation_source_refs: list[dict[str, object]] = field(default_factory=list)
    pending_question: str | None = None
    decision_log: list[DecisionLogEntry] = field(default_factory=list)
    final_route: DecisionRoute | None = None
    llm_trace: dict[str, object] | None = None

    @property
    def current_competency(self) -> Competency:
        return self.competency_order[self.current_competency_index]

    @property
    def remaining_competencies(self) -> int:
        return len(self.competency_order) - self.current_competency_index - 1

    @property
    def difficulty_label(self) -> str:
        if self.difficulty_level <= 1:
            return "low"
        if self.difficulty_level >= 3:
            return "high"
        return "medium"

    def apply_answer_feedback(self, score: float, off_topic: bool = False) -> None:
        if off_topic:
            self.difficulty_level = max(1, self.difficulty_level - 1)
            return

        if score >= self.recommendation_high_min:
            self.difficulty_level = min(3, self.difficulty_level + 1)
        elif score <= self.recommendation_low_max:
            self.difficulty_level = max(1, self.difficulty_level - 1)

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "doc_type": self.doc_type,
            "role_description": self.role_description,
            "decision_threshold": self.decision_threshold,
            "recommendation_low_max": self.recommendation_low_max,
            "recommendation_high_min": self.recommendation_high_min,
            "conclusion_threshold": self.conclusion_threshold,
            "confidence_threshold": self.confidence_threshold,
            "current_competency_index": self.current_competency_index,
            "competency_order": list(self.competency_order),
            "turn_index": self.turn_index,
            "max_turns": self.max_turns,
            "difficulty_level": self.difficulty_level,
            "off_topic_count": self.off_topic_count,
            "confidence_sum": self.confidence_sum,
            "evaluated_turns": self.evaluated_turns,
            "last_evaluation_score": self.last_evaluation_score,
            "last_evaluation_evidence": list(self.last_evaluation_evidence),
            "last_evaluation_source_refs": list(self.last_evaluation_source_refs),
            "pending_question": self.pending_question,
            "decision_log": [entry.to_dict() for entry in self.decision_log],
            "final_route": self.final_route,
            "llm_trace": self.llm_trace,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> InterviewGraphState:
        competency_order = cast(
            list[Competency],
            data.get("competency_order")
            or ["debugging", "api_design", "test_reliability"],
        )
        decision_log = cast(list[dict[str, object]], data.get("decision_log", []))

        return cls(
            role=cast(str, data["role"]),
            doc_type=cast(str, data["doc_type"]),
            role_description=cast(str, data.get("role_description", "")),
            decision_threshold=cast(float, data.get("decision_threshold", 0.75)),
            recommendation_low_max=cast(float, data.get("recommendation_low_max", 0.40)),
            recommendation_high_min=cast(float, data.get("recommendation_high_min", 0.70)),
            conclusion_threshold=cast(float, data.get("conclusion_threshold", 0.55)),
            confidence_threshold=cast(float, data.get("confidence_threshold", 0.70)),
            current_competency_index=cast(
                int, data.get("current_competency_index", 0)
            ),
            competency_order=list(competency_order),
            turn_index=cast(int, data.get("turn_index", 0)),
            max_turns=cast(int, data.get("max_turns", 5)),
            difficulty_level=cast(int, data.get("difficulty_level", 2)),
            off_topic_count=cast(int, data.get("off_topic_count", 0)),
            confidence_sum=cast(float, data.get("confidence_sum", 0.0)),
            evaluated_turns=cast(int, data.get("evaluated_turns", 0)),
            last_evaluation_score=cast(float | None, data.get("last_evaluation_score")),
            last_evaluation_evidence=cast(list[str], data.get("last_evaluation_evidence", [])),
            last_evaluation_source_refs=cast(
                list[dict[str, object]], data.get("last_evaluation_source_refs", [])
            ),
            pending_question=cast(str | None, data.get("pending_question")),
            decision_log=[DecisionLogEntry.from_dict(entry) for entry in decision_log],
            final_route=cast(DecisionRoute | None, data.get("final_route")),
            llm_trace=cast(dict[str, object] | None, data.get("llm_trace")),
        )
