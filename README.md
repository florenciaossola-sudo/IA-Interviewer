# AI Interviewer Monorepo

Phase 0 starter scaffold for the AI Interviewer project.

## Structure

- `apps/portal`: Admin and reviewer portal frontend
- `apps/interview`: Candidate interview frontend
- `services/api`: Backend API service
- `services/agent`: Agent runtime service
- `packages/shared-types`: Shared TypeScript contracts
- `packages/evals`: Evaluation fixtures and suites
- `infra`: Local infrastructure assets

## Setup

1. Install Node dependencies:
- npm install

2. Install Python tooling:
- py -3 -m pip install --user ruff mypy pytest
- py -3 -m pip install -e services/api -e services/agent
- Optional for Postgres backend:
	- py -3 -m pip install -e "services/api[postgres]" -e "services/agent[postgres]"
- Optional for DuckDB/MinIO lakehouse exports:
	- py -3 -m pip install -e "services/api[lakehouse]"

3. Optional database backend switch (default is SQLite):
- `AI_INTERVIEWER_DB_BACKEND=postgres`
- `AI_INTERVIEWER_POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/ai_interviewer`

## Verification Commands

- `npm run lint`
- `npm run typecheck`
- `npm run test`
- `npm run analytics`
- `npm run check-boundaries`
- `npm run gen:openapi` / `npm run check:openapi`
- `npm run ci`

## API Contract (Phase 1 + Grounding)

### POST /run/start

Request body:

```json
{
	"role": "backend_engineer",
	"doc_type": "role_description"
}
```

Response body:

```json
{
	"run_id": "iv_ab12cd",
	"role": "backend_engineer",
	"doc_type": "role_description",
	"question": "Tell me about a project where you had to debug a tough production issue.",
	"question_index": 1,
	"total_questions": 3,
	"completed": false,
	"grounded_context": [
		{
			"chunk_id": "backend-role::chunk-0",
			"doc_id": "backend-role",
			"doc_type": "role_description",
			"role": "backend_engineer",
			"text": "Backend engineers design reliable APIs and maintain backward compatibility.",
			"score": 0.82
		}
	],
	"citation_list": [
		{
			"source_id": "backend-role::chunk-0",
			"doc_id": "backend-role",
			"doc_type": "role_description",
			"role": "backend_engineer"
		}
	]
}
```

Field summary:

| Field | Type | Required | Description |
|---|---|---|---|
| run_id | string | yes | Interview run identifier. |
| role | string | yes | Retrieval role filter for this run. |
| doc_type | string | yes | Retrieval document-type filter for this run. |
| question | string | yes | First interviewer question from stub agent. |
| question_index | integer | yes | 1-based index of current question. |
| total_questions | integer | yes | Total number of planned interview questions. |
| completed | boolean | yes | Whether the interview has finished. |
| grounded_context | array of GroundedContextItem | yes | Retrieved chunks with full text and relevance score. |
| citation_list | array of CitationItem | yes | Deduplicated source references for audit/reviewer tracing. |

GroundedContextItem:

| Field | Type | Description |
|---|---|---|
| chunk_id | string | Unique chunk identifier used as source key. |
| doc_id | string | Document identifier where chunk came from. |
| doc_type | string | Document type of source chunk. |
| role | string | Role associated with source chunk. |
| text | string | Full chunk text used for grounding. |
| score | number | Similarity score from retrieval ranking. |

CitationItem:

| Field | Type | Description |
|---|---|---|
| source_id | string | Source identifier (maps to chunk_id). |
| doc_id | string | Document identifier for source. |
| doc_type | string | Document type for source. |
| role | string | Role associated with source. |

### POST /run/answer

Request body:

```json
{
	"run_id": "iv_ab12cd",
	"answer": "I debugged an incident by tracing API latency regressions.",
	"role": "backend_engineer",
	"doc_type": "engineering_standard"
}
```

Response body:

```json
{
	"run_id": "iv_ab12cd",
	"role": "backend_engineer",
	"doc_type": "engineering_standard",
	"question": "How do you design APIs so they remain backward compatible?",
	"question_index": 2,
	"total_questions": 3,
	"completed": false,
	"grounded_context": [
		{
			"chunk_id": "testing-standards::chunk-0",
			"doc_id": "testing-standards",
			"doc_type": "engineering_standard",
			"role": "backend_engineer",
			"text": "CI pipelines should include deterministic tests and flaky-test detection.",
			"score": 0.79
		}
	],
	"citation_list": [
		{
			"source_id": "testing-standards::chunk-0",
			"doc_id": "testing-standards",
			"doc_type": "engineering_standard",
			"role": "backend_engineer"
		}
	]
}
```

Field summary:

| Field | Type | Required | Description |
|---|---|---|---|
| run_id | string | yes | Interview run identifier. |
| role | string | yes | Effective role used for this answer retrieval pass. |
| doc_type | string | yes | Effective document-type filter used for retrieval. |
| question | string or null | yes | Next question, or null on completion. |
| question_index | integer | yes | 1-based index of the next/current question position. |
| total_questions | integer | yes | Total number of planned interview questions. |
| completed | boolean | yes | True when interview is complete. |
| grounded_context | array of GroundedContextItem | yes | Retrieved chunks for the submitted answer context. |
| citation_list | array of CitationItem | yes | Deduplicated source references for audit/reviewer tracing. |

Notes:
- `citation_list` is a compact, deduplicated source reference list for reviewer/audit usage.
- `grounded_context` contains full chunk text for runtime display.
- On final answer, `question` becomes `null` and `completed` becomes `true`.

## Notes

- Scripts are wired with real tooling for Phase 0.
- Keep live-model checks out of blocking CI jobs.
- Phase 7 analytics snapshots are generated from SQLite via `npm run analytics`.
