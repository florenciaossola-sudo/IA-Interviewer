from __future__ import annotations

from langgraph.types import Command

from services.agent.graph.checkpointing import close_checkpointed_graph, get_checkpointed_graph


def test_langgraph_pauses_for_candidate_and_human_review(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_INTERVIEWER_QUESTION_LLM_ENABLED", "0")
    monkeypatch.setenv("AI_INTERVIEWER_LLM_ENABLED", "0")
    monkeypatch.setenv("AI_INTERVIEWER_DB_BACKEND", "sqlite")
    monkeypatch.setenv("AI_INTERVIEWER_DB_PATH", str(tmp_path / "checkpoints.sqlite3"))
    interview_graph = get_checkpointed_graph()
    config = {"configurable": {"thread_id": "interrupt-test"}}

    try:
        started = interview_graph.invoke(
            {
                "role": "backend_engineer",
                "doc_type": "role_description",
                "competency_order": ["debugging"],
                "max_turns": 1,
            },
            config,
        )

        assert started["question"]
        assert interview_graph.get_state(config).next == ("await_candidate",)
        close_checkpointed_graph()
        interview_graph = get_checkpointed_graph()
        assert interview_graph.get_state(config).next == ("await_candidate",)

        paused_for_review = interview_graph.invoke(
            Command(resume="I debug production incidents using traces and rollback signals."),
            config,
        )

        assert paused_for_review["route"] in {"conclude", "escalate"}
        assert interview_graph.get_state(config).next == ("human_review",)
        assert paused_for_review.get("completed") is not True
        close_checkpointed_graph()
        interview_graph = get_checkpointed_graph()
        assert interview_graph.get_state(config).next == ("human_review",)

        reviewed = interview_graph.invoke(
            Command(resume={"decision": "approved", "rationale": "Evidence reviewed."}),
            config,
        )

        assert reviewed["completed"] is True
        assert reviewed["report"]["review_decision"] == "approved"
        assert interview_graph.get_state(config).next == ()
    finally:
        close_checkpointed_graph()