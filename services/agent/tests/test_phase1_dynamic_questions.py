from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.agent.graph.engine import LangGraphExecutionEngine, LegacyExecutionEngine
from services.agent.graph.evaluator import GroundingEvidenceRequired, evaluate_answer
from services.agent.graph.models import InterviewGraphState, RetrievalEvidence
from services.agent.graph.questions import (
    MODEL_OVERLOADED_MESSAGE,
    QuestionGeneratorError,
    _build_question_prompt,
    _post_json,
)
from services.agent.graph.runtime import InterviewGraph


class _FailingQuestionGenerator:
    def generate_question(self, state: InterviewGraphState) -> str:
        raise QuestionGeneratorError("provider unavailable")


def test_legacy_engine_returns_overload_message_when_provider_fails() -> None:
    state = InterviewGraphState(
        role="backend_engineer",
        doc_type="role_description",
        current_competency_index=1,
    )
    engine = LegacyExecutionEngine(question_generator=_FailingQuestionGenerator())

    question = engine.current_question(state)

    assert question == MODEL_OVERLOADED_MESSAGE


def test_langgraph_engine_returns_overload_message_when_provider_fails() -> None:
    state = InterviewGraphState(
        role="backend_engineer",
        doc_type="role_description",
        current_competency_index=2,
    )
    engine = LangGraphExecutionEngine(question_generator=_FailingQuestionGenerator())

    question = engine.current_question(state)

    assert question == MODEL_OVERLOADED_MESSAGE


def test_runtime_caches_question_within_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass
    class _FakeEngine:
        name: str = "fake"
        calls: int = 0

        def current_question(self, state: InterviewGraphState) -> str:
            _ = state
            self.calls += 1
            return f"q-{self.calls}"

        def run_turn(self, answer: str, state: InterviewGraphState, retrieval: object) -> str:
            _ = answer
            _ = retrieval
            state.turn_index += 1
            return "probe_deeper"

    fake_engine = _FakeEngine()

    monkeypatch.setattr(
        "services.agent.graph.runtime.create_execution_engine",
        lambda _: fake_engine,
    )

    graph = InterviewGraph(role="backend_engineer", doc_type="role_description")

    first = graph.current_question()
    second = graph.current_question()

    assert first == "q-1"
    assert second == "q-1"
    assert fake_engine.calls == 1

    step = graph.submit_answer("I use traces and logs to debug incidents.")

    assert step.completed is False
    assert step.question == "q-2"
    assert fake_engine.calls == 2
    assert graph.current_question() == "q-2"
    assert fake_engine.calls == 2


def test_role_description_is_in_question_prompt_and_difficulty_adapts() -> None:
    state = InterviewGraphState(
        role="sr_software_engineer",
        doc_type="role_description",
        role_description="Design data pipelines and agent systems for LLM-native products.",
    )

    prompt = _build_question_prompt(state)

    assert "sr_software_engineer" in prompt
    assert "Design data pipelines and agent systems for LLM-native products." in prompt
    assert "difficulty=medium" in prompt

    state.apply_answer_feedback(score=0.2)
    assert state.difficulty_level == 1
    assert state.difficulty_label == "low"

    state.apply_answer_feedback(score=0.9)
    assert state.difficulty_level == 2
    assert state.difficulty_label == "medium"


def test_model_overload_message_is_used_for_provider_failures() -> None:
    state = InterviewGraphState(
        role="backend_engineer",
        doc_type="role_description",
        current_competency_index=0,
    )
    engine = LegacyExecutionEngine(question_generator=_FailingQuestionGenerator())

    first = engine.current_question(state)
    state.turn_index = 1
    second = engine.current_question(state)

    assert first == MODEL_OVERLOADED_MESSAGE
    assert second == MODEL_OVERLOADED_MESSAGE


def test_post_json_retries_transient_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, int] = {"count": 0}

    class _DummyResponse:
        def __enter__(self) -> "_DummyResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_urlopen(req, timeout=60):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError

        return _DummyResponse()

    monkeypatch.setattr("services.agent.graph.questions.request.urlopen", fake_urlopen)

    payload = {"contents": [{"parts": [{"text": "hello"}]}]}
    result = _post_json("https://example.test/generate", payload)

    assert result == {"ok": True}
    assert calls["count"] == 2


def test_answer_evaluator_uses_relevance_depth_and_specificity() -> None:
    grounded_sources = [
        RetrievalEvidence(
            source_id="debugging::chunk-1",
            doc_id="debugging",
            text="Trace production incidents to identify root causes.",
            score=0.9,
        )
    ]
    strong = evaluate_answer(
        "I trace production incidents through logs, isolate the root cause, and compare rollout impact before changing the deployment.",
        "debugging",
        grounded_sources,
    )
    weak = evaluate_answer(
        "I like working with people and teams.", "debugging", grounded_sources
    )

    assert strong.score > 0.4
    assert strong.off_topic is False
    assert weak.off_topic is True
    assert weak.score < strong.score
    assert strong.source_refs == grounded_sources


def test_answer_evaluator_rejects_missing_corpus_evidence() -> None:
    with pytest.raises(GroundingEvidenceRequired):
        evaluate_answer("I debug production incidents.", "debugging", [])
