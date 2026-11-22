QUESTIONS: list[str] = [
    "Tell me about a project where you had to debug a tough production issue.",
    "How do you design APIs so they remain backward compatible?",
    "Describe how you would improve test reliability in a CI pipeline."
]


def total_questions() -> int:
    return len(QUESTIONS)


def get_question(index: int) -> str:
    if index < 0 or index >= len(QUESTIONS):
        raise IndexError("Question index out of range")
    return QUESTIONS[index]
