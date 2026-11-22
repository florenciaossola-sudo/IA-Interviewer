# Agent Service

The FastAPI interview workflow uses the compiled LangGraph in `graph/studio_graph.py`.
It pauses at `await_candidate` for each answer and at `human_review` before the report.
The API resumes each run by its `run_id` thread ID.

Checkpoint backends:
- SQLite is the local default; checkpoints are stored in `data/ai_interviewer.langgraph.sqlite3`.
- With `AI_INTERVIEWER_DB_BACKEND=postgres`, set `AI_INTERVIEWER_LANGGRAPH_POSTGRES_DSN`
	to a dedicated database. LangGraph uses fixed checkpoint table names that must not overlap
	the operational persistence schema.
- Install `services/agent[postgres]` to use the Postgres checkpointer.

`InterviewGraph` and `GraphExecutionEngine` remain available for deterministic policy/replay
tests and compatibility tools. The `AI_INTERVIEWER_AGENT_ENGINE` switch applies to that
runtime, not to the FastAPI interview endpoints.

LLM adapter:
- Disabled by default (`AI_INTERVIEWER_LLM_ENABLED=0`); deterministic evaluation is used.
- Enable with `AI_INTERVIEWER_LLM_ENABLED=1`.
- Provider selection: `AI_INTERVIEWER_LLM_PROVIDER=ollama|gemini|anthropic`.
- Ollama settings: `AI_INTERVIEWER_OLLAMA_ENDPOINT` and `AI_INTERVIEWER_OLLAMA_MODEL`.
- Gemini settings: `AI_INTERVIEWER_GEMINI_ENDPOINT`, `AI_INTERVIEWER_GEMINI_MODEL`,
	and `AI_INTERVIEWER_GEMINI_API_KEY`.
- Provider evaluation receives retrieved corpus chunks; provider errors fall back to the
	deterministic evaluator, while scoring without any retrieved source is rejected.

Retrieval backend:
- Default is fixture/in-memory retrieval.
- Set `AI_INTERVIEWER_RETRIEVAL_BACKEND=pgvector` and
	`AI_INTERVIEWER_POSTGRES_DSN` to use Postgres + pgvector.
- Optional settings: `AI_INTERVIEWER_RETRIEVAL_BOOTSTRAP_FIXTURE=1` and
	`AI_INTERVIEWER_RETRIEVAL_VECTOR_DIMENSIONS=256`.
