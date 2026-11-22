from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from services.agent.graph.runtime import InterviewGraph


@dataclass(frozen=True)
class ReplayFixture:
    name: str
    role: str
    doc_type: str
    answers: list[str]
    expected_final_route: str
    expected_route_sequence: list[str]


def load_fixtures() -> list[ReplayFixture]:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "golden_transcripts.json"
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [ReplayFixture(**item) for item in raw]


def run_graph_replay_eval() -> tuple[int, int]:
    fixtures = load_fixtures()
    passed = 0

    for fixture in fixtures:
        graph = InterviewGraph(role=fixture.role, doc_type=fixture.doc_type)
        result = graph.replay_answers(fixture.answers)

        if (
            result.final_route == fixture.expected_final_route
            and result.route_sequence == fixture.expected_route_sequence
        ):
            passed += 1

    return passed, len(fixtures)


def main() -> int:
    passed, total = run_graph_replay_eval()
    print(f"Graph replay fixtures passed: {passed}/{total}")

    if passed != total:
        print("FAIL: replay outputs diverge from golden expectations")
        return 1

    print("PASS: deterministic graph replay matches goldens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
