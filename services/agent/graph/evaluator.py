from __future__ import annotations

import re

from services.agent.graph.models import Competency, RetrievalEvidence, TurnEvaluation


class GroundingEvidenceRequired(ValueError):
    pass

_COMPETENCY_KEYWORDS: dict[Competency, list[str]] = {
    "debugging": ["debug", "incident", "production", "root cause", "trace", "monitoring"],
    "api_design": ["api", "version", "deprecation", "backward", "contract", "schema"],
    "test_reliability": ["test", "flaky", "ci", "deterministic", "retry", "coverage"],
}

_REASONING_MARKERS = (
    "because",
    "therefore",
    "so that",
    "tradeoff",
    "before",
    "after",
    "if",
    "when",
    "however",
    "instead",
    "for example",
)

_TECHNICAL_MARKERS = (
    "latency",
    "rollback",
    "schema",
    "retry",
    "monitoring",
    "alert",
    "contract",
    "trace",
    "bundle",
    "observability",
    "deployment",
    "ci",
    "production",
    "api",
)


def _keyword_hits(normalized: str, keywords: list[str]) -> list[str]:
    hits: list[str] = []
    for keyword in keywords:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, normalized):
            hits.append(keyword)
    return hits


def _relevance_score(normalized: str, competency: Competency) -> float:
    hits = _keyword_hits(normalized, _COMPETENCY_KEYWORDS[competency])
    total_keywords = len(_COMPETENCY_KEYWORDS[competency])
    if total_keywords == 0:
        return 0.0
    return len(hits) / total_keywords


def _depth_score(normalized: str) -> float:
    words = normalized.split()
    if not words:
        return 0.0

    reasoning_hits = sum(1 for marker in _REASONING_MARKERS if marker in normalized)
    sentence_length = min(1.0, len(words) / 40)
    reasoning_factor = min(1.0, reasoning_hits / 4)
    return min(1.0, (sentence_length * 0.6) + (reasoning_factor * 0.4))


def _specificity_score(normalized: str) -> float:
    technical_hits = sum(1 for marker in _TECHNICAL_MARKERS if marker in normalized)
    return min(1.0, technical_hits / 5)


def evaluate_answer(
    answer: str,
    competency: Competency,
    grounded_sources: list[RetrievalEvidence],
) -> TurnEvaluation:
    if not grounded_sources:
        raise GroundingEvidenceRequired("Cannot score an answer without retrieved corpus evidence")

    text = answer.lower()
    normalized = re.sub(r"\s+", " ", text).strip()

    relevance = _relevance_score(normalized, competency)
    depth = _depth_score(normalized)
    specificity = _specificity_score(normalized)
    score = min(1.0, (relevance * 0.55) + (depth * 0.30) + (specificity * 0.15))

    matched_competencies = 0
    evidence: list[str] = []

    for label, keywords in _COMPETENCY_KEYWORDS.items():
        hits = _keyword_hits(normalized, keywords)
        if hits:
            matched_competencies += 1
            evidence.append(f"{label}: {', '.join(hits)}")

    mixed_signal = matched_competencies > 1 and relevance < 0.75
    off_topic = (
        relevance <= 0.2
        and specificity <= 0.2
        and len(normalized) < 40
        and not any(marker in normalized for marker in _TECHNICAL_MARKERS)
    )

    return TurnEvaluation(
        score=score,
        off_topic=off_topic,
        mixed_signal=mixed_signal,
        evidence=evidence,
        source_refs=grounded_sources,
    )
