# API Service

Backend service for run lifecycle, reviewer actions, and audit endpoints.

Admin corpus endpoints accept PDF, DOCX, and Markdown uploads up to 15 MB, persist source files and ingestion status under `data/admin_corpus`, and support listing, re-ingestion, retry, and deletion. Install the API project dependencies to enable PDF/DOCX extraction.

Database backend selection:
- Default backend is SQLite.
- Set `AI_INTERVIEWER_DB_BACKEND=postgres` to use Postgres.
- Set `AI_INTERVIEWER_POSTGRES_DSN` when using Postgres, for example:
	- `postgresql://postgres:postgres@localhost:5432/ai_interviewer`
- Install the API and agent Postgres extras when using Postgres:
	- `py -3 -m pip install -e "services/api[postgres]" -e "services/agent[postgres]"`
- Runs, review records, checkpoints, scheduled interviews, role settings, and audit records use
	Postgres when the backend is selected. SQLite remains the local default.

OpenAPI contract:
- `npm run gen:openapi` regenerates the checked-in `openapi.json` from FastAPI routes.
- `npm run check:openapi` fails when the generated schema is missing or stale.

Current Phase 5 review surface:
- `GET /review/queue` lists completed runs awaiting review
- `POST /runs/{run_id}/review` records approve/override decisions with rationale

Scheduled interview invitations:
- Interview activation automatically sends an invitation; the Admin UI can retry a failed delivery.
- `AI_INTERVIEWER_EMAIL_BACKEND=log` (default) records a safe local delivery stub without emailing.
- For real delivery, set `AI_INTERVIEWER_EMAIL_BACKEND=resend`, `RESEND_API_KEY`, and
	`AI_INTERVIEWER_EMAIL_FROM` to a verified Resend sender address.
- Set `AI_INTERVIEWER_CANDIDATE_URL` to the externally reachable Candidate app origin; it defaults
	to `http://127.0.0.1:4174` for local development.
- Invitation tokens are encrypted at rest. Local development creates a private key file beside the
	SQLite database; deployments with multiple instances should provide a stable
	`AI_INTERVIEWER_INVITATION_ENCRYPTION_KEY` secret to every instance.
- Resend's free account may restrict recipients until the sending domain is verified. Delivery
	attempts and outcomes are recorded in interview state and the Admin audit log.
