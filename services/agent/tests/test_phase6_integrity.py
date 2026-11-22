from __future__ import annotations

from services.agent.integrity import (
    AccommodationDeclaration,
    TelemetryEvent,
    analyze_integrity,
)


def test_integrity_analyzer_respects_accommodations_and_telemetry() -> None:
    report = analyze_integrity(
        declaration=AccommodationDeclaration(
            disclosure_accepted=True,
            focus_telemetry_enabled=True,
            suppressed_signal_families=["focus"],
        ),
        telemetry_events=[
            TelemetryEvent(signal_family="focus", event_type="focus", value="answer-input"),
            TelemetryEvent(signal_family="timing", event_type="start_click", value="candidate"),
            TelemetryEvent(signal_family="input", event_type="input", value="24"),
        ],
    )

    assert report.aai_index < 100
    assert report.disposition == "reviewer_visible_only"
    assert any(
        item.signal_family == "focus" and item.suppressed
        for item in report.signal_breakdown
    )
    assert any("focus suppressed" in item for item in report.confounders)


def test_aai_uses_weighted_baseline_deviations_and_caps_content() -> None:
    declaration = AccommodationDeclaration(
        disclosure_accepted=True,
        focus_telemetry_enabled=True,
        suppressed_signal_families=[],
    )
    weights = {"focus": 0, "timing": 1, "input": 0, "motion": 0, "content": 0}

    baseline = analyze_integrity(
        declaration=declaration,
        telemetry_events=[],
        signal_weights=weights,
        signal_deviations={"timing": 0.0},
    )
    anomalous = analyze_integrity(
        declaration=declaration,
        telemetry_events=[],
        signal_weights=weights,
        signal_deviations={"timing": 0.5},
    )
    accommodated = analyze_integrity(
        declaration=AccommodationDeclaration(
            disclosure_accepted=True,
            focus_telemetry_enabled=True,
            suppressed_signal_families=["timing"],
        ),
        telemetry_events=[],
        signal_weights=weights,
        signal_deviations={"timing": 1.0},
    )
    content = analyze_integrity(
        declaration=declaration,
        telemetry_events=[],
        signal_weights={**weights, "timing": 0, "content": 1},
        signal_deviations={"content": 1.0},
        ai_text_cap=0.1,
    )

    assert baseline.aai_index == 0
    assert anomalous.aai_index == 50
    assert accommodated.aai_index == 0
    assert content.aai_index == 10