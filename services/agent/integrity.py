from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

SignalFamily = Literal["focus", "timing", "input", "motion", "content"]


@dataclass(frozen=True)
class TelemetryEvent:
    signal_family: SignalFamily
    event_type: str
    value: str


@dataclass(frozen=True)
class AccommodationDeclaration:
    disclosure_accepted: bool
    focus_telemetry_enabled: bool
    suppressed_signal_families: list[SignalFamily]


@dataclass(frozen=True)
class IntegritySignalBreakdown:
    signal_family: SignalFamily
    event_count: int
    suppressed: bool
    evidence: list[str]


@dataclass(frozen=True)
class IntegrityReport:
    disclosure_accepted: bool
    focus_telemetry_enabled: bool
    aai_index: int
    signal_breakdown: list[IntegritySignalBreakdown]
    confounders: list[str]
    disposition: str
    suppressed_signal_families: list[SignalFamily]


def analyze_integrity(
    declaration: AccommodationDeclaration,
    telemetry_events: list[TelemetryEvent],
    signal_weights: dict[str, int] | None = None,
    max_penalty: int = 100,
    ai_text_cap: float = 0.1,
    signal_deviations: dict[str, float] | None = None,
) -> IntegrityReport:
    event_counts: dict[SignalFamily, int] = {
        "focus": 0, "timing": 0, "input": 0, "motion": 0, "content": 0
    }
    weights = signal_weights or {}
    deviations = signal_deviations or {}
    for event in telemetry_events:
        event_counts[event.signal_family] += 1

    signal_breakdown = []
    confounders: list[str] = []
    weighted_deviation = 0.0
    available_weight = 0

    for family, count in event_counts.items():
        suppressed = family in declaration.suppressed_signal_families
        family_events = [event for event in telemetry_events if event.signal_family == family]
        signal_breakdown.append(
            IntegritySignalBreakdown(
                signal_family=family,
                event_count=count,
                suppressed=suppressed,
                evidence=[f"{event.event_type}: {event.value}" for event in family_events],
            )
        )
        if suppressed:
            confounders.append(f"{family} suppressed by accommodation")
            continue

        if family == "focus" and not declaration.focus_telemetry_enabled:
            confounders.append("focus telemetry disabled by default")
            continue

        weight = weights.get(family, 3)
        if weight <= 0 or family not in deviations:
            continue
        deviation = deviations.get(family, 0.0)
        if not isfinite(deviation):
            deviation = 0.0
        deviation = min(1.0, max(0.0, deviation))
        if family == "content":
            deviation = min(deviation, min(0.1, max(0.0, ai_text_cap)))
        weighted_deviation += deviation * weight
        available_weight += weight

    weighted_mean = weighted_deviation / available_weight if available_weight else 0.0
    aai_index = min(100, round(weighted_mean * max(0, max_penalty)))
    if not declaration.disclosure_accepted:
        aai_index = min(100, aai_index + 6)

    if not declaration.disclosure_accepted:
        confounders.append("disclosure not accepted")

    if not declaration.focus_telemetry_enabled:
        confounders.append("focus telemetry off")

    if declaration.suppressed_signal_families:
        confounders.append(
            "accommodations declared: "
            + ", ".join(sorted(declaration.suppressed_signal_families))
        )

    disposition = "reviewer_attention_needed" if aai_index >= 50 else "reviewer_visible_only"

    return IntegrityReport(
        disclosure_accepted=declaration.disclosure_accepted,
        focus_telemetry_enabled=declaration.focus_telemetry_enabled,
        aai_index=aai_index,
        signal_breakdown=signal_breakdown,
        confounders=confounders,
        disposition=disposition,
        suppressed_signal_families=declaration.suppressed_signal_families,
    )