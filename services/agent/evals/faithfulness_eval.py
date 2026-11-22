from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FaithfulnessResult:
    total_claims: int
    supported_claims: int
    unsupported_claims: tuple[str, ...]

    @property
    def score(self) -> float:
        return self.supported_claims / self.total_claims if self.total_claims else 1.0


def evaluate_claims(claims: list[str], evidence: list[str]) -> FaithfulnessResult:
    normalized_evidence = " ".join(evidence).casefold()
    unsupported = tuple(
        claim for claim in claims
        if claim.strip().casefold() not in normalized_evidence
    )
    return FaithfulnessResult(
        total_claims=len(claims),
        supported_claims=len(claims) - len(unsupported),
        unsupported_claims=unsupported,
    )


def assert_faithful(claims: list[str], evidence: list[str]) -> FaithfulnessResult:
    result = evaluate_claims(claims, evidence)
    if result.unsupported_claims:
        raise ValueError(f"Unsupported report claims: {result.unsupported_claims}")
    return result


if __name__ == "__main__":
    assert_faithful(["The score is grounded by tracing"], ["The score is grounded by tracing"])