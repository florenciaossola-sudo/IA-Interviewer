# AI Interviewer

AI Interviewer is a platform for adaptive technical interviews. Administrators
prepare roles and interviews, candidates answer questions, and reviewers inspect
the evidence and make a human decision. The system assists the process; it does
not make an automatic hiring decision.

## Features

- **Admin:** manage roles, interview schedules, candidate links, reviewers and
  source documents.
- **Candidate:** complete a warm-up and an adaptive interview, with support for
  resuming an interrupted session.
- **Reviewer:** inspect answers, scores, retrieved sources, checkpoints and
  integrity signals, and accept or override the system recommendation.
- **Workflow:** FastAPI handles requests and LangGraph coordinates question
  generation, retrieval, evaluation, routing and human review.
- **Grounding:** retrieval supplies relevant document chunks to the evaluator.
  Question generation and answer evaluation can use separately configured models.

## Project structure

| Directory | Purpose |
| --- | --- |
| `apps/portal` | Admin and Reviewer frontends |
| `apps/interview` | Candidate frontend |
| `services/api` | FastAPI endpoints and persistence |
| `services/agent` | Interview workflow, evaluation and retrieval |
| `services/analytics` | Analytics and reporting |
| `packages/shared-types` | Shared TypeScript contracts |
| `packages/evals` | Evaluation resources |
| `infra` | Optional PostgreSQL, pgvector and other local infrastructure |
| `docs` | Presentation and technical documentation |

## Requirements

- Git.
- Node.js 22 and npm. The version used by CI is recorded in `.nvmrc`.
- Python 3.12 or newer; CI uses Python 3.12.
- Optional: Ollama and a local model for LLM-powered interviews.
- Optional: Docker and Docker Compose for PostgreSQL and pgvector.

The commands below use **Windows PowerShell** and assume you run them from the
repository root. Other operating systems require their equivalent commands.

## Clone and install

```powershell
git clone https://github.com/florenciaossola-sudo/IA-Interviewer.git
cd IA-Interviewer

npm ci
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e services\api -e services\agent
```

The virtual environment is used explicitly, so activation is not required.
`py -3.12` requires Python 3.12 to be installed and available to the Windows
Python launcher.

For the optional test and quality tools:

```powershell
.\.venv\Scripts\python.exe -m pip install ruff mypy pytest
```

## Start the application

Open **four PowerShell terminals** in the repository root. Start the API first
and leave all four processes running:

**Terminal 1 - API**

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.api.main:app --host 127.0.0.1 --port 8081 --reload
```

**Terminal 2 - Admin**

```powershell
npm run dev --workspace @ai-interviewer/portal
```

**Terminal 3 - Candidate**

```powershell
npm run dev --workspace @ai-interviewer/interview
```

**Terminal 4 - Reviewer**

```powershell
npm run dev:reviewer --workspace @ai-interviewer/portal
```

| Service | Local address |
| --- | --- |
| Admin | http://127.0.0.1:4173 |
| Candidate | http://127.0.0.1:4174 |
| Reviewer | http://127.0.0.1:4175 |
| FastAPI interactive documentation | http://127.0.0.1:8081/docs |

Stop each process with `Ctrl+C` in its terminal.

## Try an interview

1. In Admin, create a role with a meaningful description. Add PDF, DOCX or
   Markdown documents to the corpus as needed, using the matching role and
   document type. Confirm that ingestion succeeded.
2. Schedule an interview for that role, set an expiration time and copy the
   candidate link. Assign a reviewer. The interview must be active and not
   expired; it can be activated manually or when its scheduled time arrives.
3. Open the candidate link, accept the integrity disclosure, choose any
   applicable accommodations and complete the warm-up and interview.
4. Open Reviewer, select the completed run from the queue or load its run ID.
   Examine the transcript, evaluations and sources, then submit an **approved**
   or **overridden** recommendation with a rationale. Approved means accepting
   the system recommendation, not automatically hiring the candidate.

The default invitation backend logs delivery instead of sending email. For real
email delivery, see [the API service guide](services/api/README.md).

## Database and local data

The default setup uses SQLite and does not require a separate database server.
The application creates local data under `data/`, including operational records,
scheduled interviews, LangGraph checkpoints and uploaded corpus documents. The
directory, local invitation encryption keys and `.env` files are ignored by Git.
A fresh clone does **not** contain your existing interviews, roles or uploaded
documents. Keep backups private: these files can contain personal information.

The default retrieval backend uses an in-memory index and sample documents. It is
configured separately from the operational database.

### Optional: PostgreSQL and pgvector

From the repository root, install the PostgreSQL extras and start the local
PostgreSQL container:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "services\api[postgres]" -e "services\agent[postgres]"
docker compose -f infra\docker-compose.yml up -d postgres
```

In the **API terminal**, set these local-development variables before starting
Uvicorn:

```powershell
$env:AI_INTERVIEWER_DB_BACKEND = "postgres"
$env:AI_INTERVIEWER_POSTGRES_DSN = "postgresql://aiuser:local-dev-only@127.0.0.1:5432/ai_interviewer"
$env:AI_INTERVIEWER_LANGGRAPH_POSTGRES_DSN = "postgresql://aiuser:local-dev-only@127.0.0.1:5432/ai_interviewer_langgraph"

# Optional: use pgvector for retrieval as well.
$env:AI_INTERVIEWER_RETRIEVAL_BACKEND = "pgvector"

.\.venv\Scripts\python.exe -m uvicorn services.api.main:app --host 127.0.0.1 --port 8081 --reload
```

These credentials are the Compose defaults for local development only. Replace
them for shared environments. LangGraph requires its own database because its
checkpoint tables must not overlap with the operational schema. Choosing
PostgreSQL for operational data does not automatically enable pgvector.
See [the infrastructure guide](infra/README.md) for additional options.

## Models and grounding

By default, answer evaluation uses deterministic rules and question generation
uses deterministic prompts when no provider is enabled. A Gemini key present in
the environment can auto-enable Gemini question generation; remove it from the
API process environment if a fully deterministic run is required. Evaluation
still requires retrieved source evidence.

To use **Ollama** for both questions and evaluation, install and start Ollama,
download a model such as `llama3.1`, and set the variables in the API terminal
before starting the API:

```powershell
ollama pull llama3.1
$env:AI_INTERVIEWER_QUESTION_LLM_ENABLED = "1"
$env:AI_INTERVIEWER_QUESTION_LLM_PROVIDER = "ollama"
$env:AI_INTERVIEWER_LLM_ENABLED = "1"
$env:AI_INTERVIEWER_LLM_PROVIDER = "ollama"
$env:AI_INTERVIEWER_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
$env:AI_INTERVIEWER_OLLAMA_MODEL = "llama3.1"

.\.venv\Scripts\python.exe -m uvicorn services.api.main:app --host 127.0.0.1 --port 8081 --reload
```

Question generation and evaluation can be enabled independently. Gemini and
Anthropic are also supported; question generation additionally supports GitHub
Models. See [the agent guide](services/agent/README.md) and
[question provider configuration](services/agent/graph/questions.py) for the
relevant variables. Store API keys outside the repository. PowerShell environment
variables apply to the current terminal and its child processes.

For grounding, documents are split into chunks and indexed. The current embedder
uses normalized token frequencies, not a neural semantic embedding model.
Relevant chunks are retrieved by role and document type and supplied to the
evaluator. A retrieval similarity score is not a candidate score. See
[RAG in the project](docs/rag-en-el-proyecto.md) for a detailed explanation
in Spanish.

## API

With the API running, use [Swagger UI](http://127.0.0.1:8081/docs) or
[ReDoc](http://127.0.0.1:8081/redoc) for the current request and response
schemas. The repository also contains [openapi.json](openapi.json).

| Endpoint | Purpose |
| --- | --- |
| `POST /run/start` | Start or resume an interview run. |
| `POST /run/answer` | Submit a warm-up or interview answer and continue the workflow. |
| `GET /runs/{run_id}/audit` | Retrieve the run's audit information. |
| `POST /runs/{run_id}/review` | Submit a human review. |
| `/admin/roles` and `/admin/interviews` | Manage roles and scheduled interviews. |

## Tests and checks

The root npm scripts invoke Python through `py -3`, which may select a different
interpreter from the virtual environment. Install the project and quality tools
in the interpreter selected by the launcher before using those scripts. To run
Python tests explicitly with the project environment instead:

```powershell
.\.venv\Scripts\python.exe -m pytest services\api\tests services\agent\tests services\analytics\tests
```

Other checks:

```powershell
npm run lint
npm run typecheck
npm run test
npm run test --workspace @ai-interviewer/portal
npm run check-boundaries
npm run check:openapi
```

`npm run gen:openapi` regenerates the checked-in schema. `npm run ci` runs the
larger set of checks and end-to-end suites; browser tests additionally require
Playwright's Chromium (`npx playwright install chromium`).

## Privacy and limitations

- Reviewer integrity signals are contextual review aids, not proof of
  misconduct, probabilities of fraud or technical competency scores. Focus
  telemetry is optional and declared accommodations can suppress signals.
- The reviewer can accept or override the system recommendation; a human
  remains responsible for interpreting evidence.
- The decision, conclusion and confidence thresholds currently used by the
  graph are fixed defaults rather than the corresponding per-role settings.
- Admin endpoints are not authenticated. This local setup is not suitable for
  exposure to untrusted networks without additional security controls. Reviewer
  authentication can be enabled; see [the portal guide](apps/portal/README.md).
- Do not commit credentials, candidate data, generated databases or private
  source documents. Use non-production data for local demonstrations.
