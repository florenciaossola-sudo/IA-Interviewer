from services.agent import stub_agent


def agent_name() -> str:
    return "ai-interviewer-stub-agent"


def planned_question_count() -> int:
    return stub_agent.total_questions()
