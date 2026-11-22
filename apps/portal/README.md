# Portal App

Admin and reviewer UI built with React + Vite.

Admin responsibilities:
- Manage roles and per-role interview policy (thresholds, recommendation bands, turns, persona, question guidance).
- Manage the corpus: upload PDF/DOCX/Markdown, inspect ingestion state, retry/re-ingest, and delete indexed content.
- Schedule interviews, search/filter/page, import/export CSV, manage candidate links, and assign reviewers.
- Run analytics syncs, inspect sync history, snapshots, comparisons, and global Admin audit events.
- Configure integrity signal weights, penalty limit, and the cap for content events.

Reviewer responsibilities:
- Work the completed-run review queue and load an individual run by ID.
- Inspect persisted run metadata, the ordered transcript/event stream, checkpoints, decision details, and integrity appendix.
- Approve or override with mandatory rationale and record an integrity disposition with rationale.

Boundaries and current limitations:
- The Reviewer console does not run analytics syncs or edit Admin configuration.
- Interview activation is automatic on schedule; candidate notifications use the configured notifier (`log` by default, Resend when enabled).
- The AI-text cap applies only to `content` telemetry events; this project does not currently generate an AI-text detector signal.
- Reviewer authentication can be enabled with `AI_INTERVIEWER_REVIEWER_AUTH_KEY`; Admin endpoints remain unauthenticated and should not be exposed to untrusted networks.
- Audit actor values are supplied by the UI or default to `local-admin`.

Planned screens:
- dashboard
- interviews list/detail
- reviews queue/detail
- corpus and role configuration
