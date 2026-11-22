import io
import json
from urllib import error

from services.agent.graph.llm import AnthropicLlmAdapter, build_llm_adapter_from_environment
from services.agent.graph.questions import (
    AnthropicQuestionGenerator,
    GeminiQuestionGenerator,
    QuestionGeneratorError,
    _post_json,
    build_question_generator_from_environment,
)


def test_anthropic_provider_selection(monkeypatch) -> None:
    monkeypatch.setenv("AI_INTERVIEWER_LLM_ENABLED", "1")
    monkeypatch.setenv("AI_INTERVIEWER_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AI_INTERVIEWER_ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AI_INTERVIEWER_ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

    adapter = build_llm_adapter_from_environment()
    assert isinstance(adapter, AnthropicLlmAdapter)

    monkeypatch.setenv("AI_INTERVIEWER_QUESTION_LLM_ENABLED", "1")
    monkeypatch.setenv("AI_INTERVIEWER_QUESTION_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AI_INTERVIEWER_QUESTION_ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AI_INTERVIEWER_QUESTION_ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

    generator = build_question_generator_from_environment()
    assert isinstance(generator, AnthropicQuestionGenerator)


def test_post_json_includes_http_error_body(monkeypatch) -> None:
    class FakeHttpError(error.HTTPError):
        def __init__(self) -> None:
            super().__init__(
                url="https://api.anthropic.com/v1/messages",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=None,
            )

    def fake_urlopen(req, timeout=60):
        payload = json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": "model is not available"}}).encode("utf-8")
        raise error.HTTPError(req.full_url, 400, "Bad Request", req.headers, io.BytesIO(payload))

    monkeypatch.setattr("services.agent.graph.questions.request.urlopen", fake_urlopen)

    try:
        _post_json(
            "https://api.anthropic.com/v1/messages",
            {"model": "claude-3-5-haiku-20241022", "messages": [{"role": "user", "content": "hi"}]},
            api_key="test-key",
            extra_headers={"anthropic-version": "2023-06-01"},
        )
    except QuestionGeneratorError as exc:
        assert "model is not available" in str(exc)
    else:
        raise AssertionError("Expected QuestionGeneratorError to be raised")


def test_gemini_question_generates_from_all_text_parts(monkeypatch) -> None:
    generator = GeminiQuestionGenerator(
        endpoint="https://generativelanguage.googleapis.com",
        model="gemini-3.6-flash",
        api_key="test-key",
    )

    def fake_post_json(url, payload, api_key=None, extra_headers=None):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "How would you "},
                            {"text": "debug a slow backend API?"},
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr("services.agent.graph.questions._post_json", fake_post_json)

    text = generator.generate_question(
        type("State", (), {"role": "backend_engineer", "doc_type": "role_description", "current_competency": "debugging", "turn_index": 0, "max_turns": 3, "remaining_competencies": ["debugging"], "difficulty_label": "medium"})()
    )

    assert text == "How would you debug a slow backend API?"
