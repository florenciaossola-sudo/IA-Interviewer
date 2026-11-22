from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _openapi_path() -> Path:
    return Path(__file__).resolve().parents[2] / "openapi.json"


def _build_schema() -> dict[str, Any]:
    temporary_directory = tempfile.TemporaryDirectory(prefix="ai-interviewer-openapi-")
    os.environ["AI_INTERVIEWER_DB_BACKEND"] = "sqlite"
    os.environ["AI_INTERVIEWER_DB_PATH"] = str(Path(temporary_directory.name) / "runs.sqlite3")
    os.environ["AI_INTERVIEWER_INTERVIEW_DB_PATH"] = str(
        Path(temporary_directory.name) / "interviews.sqlite3"
    )
    os.environ["AI_INTERVIEWER_RETRIEVAL_BACKEND"] = "fixture"
    os.environ["AI_INTERVIEWER_QUESTION_LLM_ENABLED"] = "0"
    os.environ["AI_INTERVIEWER_LLM_ENABLED"] = "0"

    from services.api.main import app

    schema = app.openapi()
    temporary_directory.cleanup()
    return schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or verify the FastAPI OpenAPI schema.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true", help="Write openapi.json from API routes")
    action.add_argument("--check", action="store_true", help="Fail if openapi.json is stale")
    args = parser.parse_args(argv)

    rendered = json.dumps(_build_schema(), indent=2, sort_keys=True) + "\n"
    output_path = _openapi_path()
    if args.write:
        output_path.write_text(rendered, encoding="utf-8")
        print(f"Wrote {output_path}")
        return 0

    if not output_path.exists() or output_path.read_text(encoding="utf-8") != rendered:
        print("OpenAPI schema is missing or stale; run `npm run gen:openapi`.", file=sys.stderr)
        return 1
    print("OpenAPI schema is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())