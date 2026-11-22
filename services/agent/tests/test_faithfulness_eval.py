from services.agent.evals.faithfulness_eval import assert_faithful, evaluate_claims


def test_faithfulness_flags_unsupported_claims() -> None:
    result = evaluate_claims(
        ["The score is grounded", "The candidate used a hidden tool"],
        ["The score is grounded by the retrieved corpus chunk."],
    )
    assert result.supported_claims == 1
    assert result.unsupported_claims == ("The candidate used a hidden tool",)


def test_faithfulness_accepts_supported_claims() -> None:
    result = assert_faithful(["The score is grounded"], ["The score is grounded by evidence."])
    assert result.score == 1.0