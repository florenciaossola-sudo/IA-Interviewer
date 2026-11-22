from __future__ import annotations

from services.agent.graph.models import DecisionContext, DecisionRoute


def decide_route(context: DecisionContext) -> DecisionRoute:
    """Adaptive routing policy with coverage, confidence, and safety constraints."""
    # Escalate early when quality is repeatedly off-topic.
    if context.off_topic_count >= 2:
        return "escalate"

    turns_after_this = context.max_turns - (context.turn_index + 1)
    average_confidence = (
        context.cumulative_score_before_turn + context.score
    ) / (context.evaluated_turns_before_turn + 1)

    # Enforce minimum competency coverage: switch when we are running out of turns.
    if context.remaining_competencies > 0 and turns_after_this <= context.remaining_competencies:
        return "switch_competency"

    if context.mixed_signal and context.remaining_competencies > 0:
        return "switch_competency"

    if context.score >= context.decision_threshold and context.remaining_competencies > 0:
        return "switch_competency"

    # Conclude only with complete coverage and healthy accumulated confidence.
    if (
        context.remaining_competencies == 0
        and average_confidence >= context.confidence_threshold
        and context.score >= context.conclusion_threshold
    ):
        return "conclude"

    # The safety budget blocks probing after the final allowed answer.
    if context.turn_index >= context.max_turns - 1:
        return "escalate"

    if context.score >= 0.45:
        return "probe_deeper"

    return "probe_deeper"
