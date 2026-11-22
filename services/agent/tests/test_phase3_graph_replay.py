from services.agent.evals.graph_replay_eval import run_graph_replay_eval


def test_golden_replay_fixtures() -> None:
    passed, total = run_graph_replay_eval()
    assert passed == total
