from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.agent.graph.engine import LangGraphExecutionEngine, LegacyExecutionEngine
from services.agent.graph.llm import (
    LlmAdapterError,
    LlmTurnAssessment,
    OllamaLlmAdapter,
    _assessment_from_json_text,
    _post_json,
)
from services.agent.graph.models import InterviewGraphState, RetrievalEvidence
from services.agent.retrieval.service import GroundedRetrievalService


class _FailingAdapter:
    def assess_turn(
        self,
        *,
        answer: str,
        competency: str,
        role: str,
        doc_type: str,
        grounded_sources,
    ) -> LlmTurnAssessment:
        _ = answer, competency, role, doc_type, grounded_sources
        raise LlmAdapterError("provider unavailable")


class _EscalatingAdapter:
    def assess_turn(
        self,
        *,
        answer: str,
        competency: str,
        role: str,
        doc_type: str,
        grounded_sources,
    ) -> LlmTurnAssessment:
        _ = answer, competency, role, doc_type, grounded_sources
        return LlmTurnAssessment(
            score=0.95,
            off_topic=True,
            mixed_signal=False,
            evidence=["forced-off-topic"],
            provider="test",
            model="stub",
        )


def _fixture_service() -> GroundedRetrievalService:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "corpus.json"
    return GroundedRetrievalService.from_fixture(fixture_path)


def test_langgraph_falls_back_to_deterministic_when_llm_errors() -> None:
    retrieval = _fixture_service()
    answer = "I preserve compatibility through versioned APIs and migration notes."

    baseline_state = InterviewGraphState(role="backend_engineer", doc_type="role_description")
    fallback_state = InterviewGraphState.from_dict(baseline_state.to_dict())

    legacy_engine = LegacyExecutionEngine()
    legacy_route = legacy_engine.run_turn(answer=answer, state=baseline_state, retrieval=retrieval)

    langgraph_engine = LangGraphExecutionEngine(llm_adapter=_FailingAdapter())
    langgraph_route = langgraph_engine.run_turn(
        answer=answer,
        state=fallback_state,
        retrieval=retrieval,
    )

    assert langgraph_route == legacy_route
    assert fallback_state.turn_index == baseline_state.turn_index
    assert fallback_state.decision_log[-1].reason == baseline_state.decision_log[-1].reason
    assert fallback_state.llm_trace is not None
    assert fallback_state.llm_trace["provider"] == "deterministic"
    assert fallback_state.llm_trace["fallback_used"] is True
    assert fallback_state.llm_trace["engine"] == "langgraph"


def test_langgraph_uses_llm_assessment_when_valid() -> None:
    retrieval = _fixture_service()
    state = InterviewGraphState(role="backend_engineer", doc_type="role_description")
    state.off_topic_count = 1

    engine = LangGraphExecutionEngine(llm_adapter=_EscalatingAdapter())
    route = engine.run_turn(
        answer="I debug production incidents by checking traces and rollback signals.",
        state=state,
        retrieval=retrieval,
    )

    assert route == "escalate"
    assert state.final_route == "escalate"
    assert state.llm_trace is not None
    assert state.llm_trace["provider"] == "test"
    assert state.llm_trace["model"] == "stub"
    assert state.llm_trace["fallback_used"] is False
    assert state.llm_trace["engine"] == "langgraph"


def test_llm_payload_validation_rejects_invalid_shapes() -> None:
    with pytest.raises(LlmAdapterError):
        _assessment_from_json_text(
            "{not-json}", provider="test", model="stub", answer="Candidate answer"
        )

    with pytest.raises(LlmAdapterError):
        _assessment_from_json_text(
            '{"score":"high","off_topic":false,"mixed_signal":false,"evidence":[]}',
            provider="test",
            model="stub",
            answer="Candidate answer",
        )

    valid = _assessment_from_json_text(
        '{"score":0.5,"off_topic":false,"mixed_signal":true,"evidence":["fixed a deadlock"]}',
        provider="test",
        model="stub",
        answer="I fixed a deadlock with Kafka.",
    )
    assert valid.score == 0.5
    assert valid.mixed_signal is True

    fenced = _assessment_from_json_text(
        '```\n{"score":0.8,"off_topic":false,"mixed_signal":false,"evidence":["fixed a deadlock"]}\n```',
        provider="ollama",
        model="llama3.1",
        answer="I fixed a deadlock with Kafka.",
    )
    assert fenced.score == 0.8
    assert fenced.evidence == ["fixed a deadlock"]


def test_llm_keeps_score_and_unverified_evidence(caplog) -> None:
    assessment = _assessment_from_json_text(
        '{"score":0.8,"off_topic":false,"mixed_signal":false,"evidence":['
        '"Design, develop and maintain enterprise-scale web applications.",'
        '"Write and maintain unit tests."]}',
        provider="ollama",
        model="llama3.1",
        answer="I fixed a production incident using traces and regression tests.",
    )

    assert assessment.score == 0.8
    assert assessment.evidence == [
        "Design, develop and maintain enterprise-scale web applications.",
        "Write and maintain unit tests.",
    ]
    assert "unverified candidate quotations" in caplog.text


def test_llm_keeps_all_evidence_in_fenced_json() -> None:
    evidence = [f"example {i}" for i in range(12)]
    response = json.dumps(
        {"score": 0.9, "off_topic": False, "mixed_signal": False, "evidence": evidence}
    )
    assessment = _assessment_from_json_text(
        f"```json\n{response}\n```",
        provider="ollama",
        model="llama3.1",
        answer=" ".join(evidence),
    )
    assert assessment.score == 0.9
    assert assessment.evidence == evidence


@pytest.mark.parametrize("score", ["true", "NaN", "1.1", "-0.1"])
def test_llm_rejects_invalid_numeric_scores(score: str) -> None:
    with pytest.raises(LlmAdapterError):
        _assessment_from_json_text(
            '{"score":' + score + ',"off_topic":false,"mixed_signal":false,"evidence":[]}',
            provider="test",
            model="stub",
            answer="Candidate answer",
        )


def test_studio_keeps_llm_score_and_evidence(monkeypatch, caplog) -> None:
    from services.agent.graph import studio_graph

    class Adapter:
        def assess_turn(self, **kwargs):
            return _assessment_from_json_text(
                '{"score":0.8,"off_topic":false,"mixed_signal":false,'
                '"evidence":["Design, develop and maintain enterprise-scale web applications."]}',
                provider="ollama",
                model="llama3.1",
                answer=kwargs["answer"],
            )

    monkeypatch.setattr(studio_graph, "build_llm_adapter_from_environment", lambda: Adapter())
    state = {
        "answer": "I investigated production timeouts with traces.",
        "competency_order": ["debugging", "api_design"],
        "grounded_context": [{"source_id": "role::chunk-0", "doc_id": "role", "text": "Role", "score": 0.5}],
    }
    evaluated = studio_graph.evaluate_node(state)
    decided = studio_graph.decide_node({**state, **evaluated})

    assert evaluated["score"] == 0.8
    assert evaluated["fallback_used"] is False
    assert evaluated["provider"] == "ollama"
    assert evaluated["evidence"] == ["Design, develop and maintain enterprise-scale web applications."]
    assert decided["route"] == "switch_competency"
    assert decided["llm_trace"]["provider"] == "ollama"
    assert "unverified candidate quotations" in caplog.text


def test_ollama_keeps_model_evidence_and_original_score(monkeypatch) -> None:
    answer = "We reduced write latency by 45% with asynchronous replication."
    responses = iter([{
        "response": (
            '{"score":0.9,"off_topic":false,"mixed_signal":false,'
            '"evidence":["Senior DBA role requirements",'
            '"The candidate reduced write latency by 45% with asynchronous replication"]}'
        )
    }])
    requests = []

    def post_json(url, payload):
        requests.append((url, payload))
        return next(responses)

    monkeypatch.setattr("services.agent.graph.llm._post_json", post_json)
    assessment = OllamaLlmAdapter("http://ollama", "llama3.1").assess_turn(
        answer=answer,
        competency="debugging",
        role="backend_engineer",
        doc_type="role_description",
        grounded_sources=[
            RetrievalEvidence(
                source_id="role::chunk-0",
                doc_id="role",
                text="Senior DBA role requirements",
                score=0.8,
            )
        ],
    )

    assert assessment.score == 0.9
    assert assessment.evidence == [
        "Senior DBA role requirements",
        "The candidate reduced write latency by 45% with asynchronous replication",
    ]
    assert len(requests) == 1


def test_llm_http_timeout_becomes_recoverable_adapter_error(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr("services.agent.graph.llm.request.urlopen", timeout)

    with pytest.raises(LlmAdapterError, match="timed out"):
        _post_json("http://127.0.0.1:11434/api/generate", {"prompt": "test"})
