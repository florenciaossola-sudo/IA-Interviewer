from __future__ import annotations

import os

from services.agent.graph.runtime import InterviewGraph


def test_langgraph_engine_matches_legacy_routes() -> None:
    answers = [
        "I isolate incidents with logs, traces, and reproducible test cases.",
        "I preserve compatibility through versioned APIs and migration notes.",
        "I stabilize CI by fixing flaky tests and instrumenting regressions.",
    ]

    original = os.environ.get("AI_INTERVIEWER_AGENT_ENGINE")
    try:
        os.environ["AI_INTERVIEWER_AGENT_ENGINE"] = "legacy"
        legacy = InterviewGraph(role="backend_engineer", doc_type="role_description")
        legacy_result = legacy.replay_answers(answers)

        os.environ["AI_INTERVIEWER_AGENT_ENGINE"] = "langgraph"
        langgraph = InterviewGraph(role="backend_engineer", doc_type="role_description")
        langgraph_result = langgraph.replay_answers(answers)
    finally:
        if original is None:
            os.environ.pop("AI_INTERVIEWER_AGENT_ENGINE", None)
        else:
            os.environ["AI_INTERVIEWER_AGENT_ENGINE"] = original

    assert legacy_result.final_route == langgraph_result.final_route
    assert legacy_result.route_sequence == langgraph_result.route_sequence
    assert [item.route for item in legacy_result.decision_log] == [
        item.route for item in langgraph_result.decision_log
    ]
    assert all(item.node != "report" for item in legacy_result.decision_log)
    assert all(item.node != "report" for item in langgraph_result.decision_log)
