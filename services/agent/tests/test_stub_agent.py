import pytest

from services.agent import runtime, stub_agent


def test_stub_agent_has_three_questions() -> None:
    assert stub_agent.total_questions() == 3
    assert runtime.planned_question_count() == 3


def test_stub_agent_returns_first_question() -> None:
    question = stub_agent.get_question(0)
    assert "project" in question.lower() or "debug" in question.lower()


def test_stub_agent_rejects_invalid_index() -> None:
    with pytest.raises(IndexError):
        stub_agent.get_question(100)
