# Contributing

## Phase 0 rules

- Preserve package boundaries:
  - apps may depend on services by API contracts and on packages
  - services may depend on packages
  - packages must not depend on apps or services
- Keep CI deterministic (no live model calls in blocking checks).
- Add tests with every behavior change.

## Pull request checks

- lint
- typecheck
- test
- deterministic evals
- boundary checks
- OpenAPI freshness
- Candidate and Reviewer browser E2E
