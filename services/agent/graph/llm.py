from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib import error, request

from services.agent.graph.models import Competency, RetrievalEvidence


class LlmAdapterError(RuntimeError):
    pass


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmTurnAssessment:
    score: float
    off_topic: bool
    mixed_signal: bool
    evidence: list[str]
    provider: str
    model: str


class LlmAdapter(Protocol):
    def assess_turn(
        self,
        *,
        answer: str,
        competency: Competency,
        role: str,
        doc_type: str,
        grounded_sources: list[RetrievalEvidence],
    ) -> LlmTurnAssessment:
        ...


class OllamaLlmAdapter:
    def __init__(self, endpoint: str, model: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model

    def assess_turn(
        self,
        *,
        answer: str,
        competency: Competency,
        role: str,
        doc_type: str,
        grounded_sources: list[RetrievalEvidence],
    ) -> LlmTurnAssessment:
        prompt = _build_evaluation_prompt(
            answer=answer,
            competency=competency,
            role=role,
            doc_type=doc_type,
            grounded_sources=grounded_sources,
        )
        payload = {"model": self._model, "stream": False, "prompt": prompt}
        print("[DEBUG] Ollama payload:\n" + json.dumps(payload, ensure_ascii=False, indent=2))

        # Persist the full evaluation prompt/payload for reliable debugging (Ollama)
        try:
            debug_path = Path(os.getcwd()) / "tmp" / "llm_eval_debug.log"
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            with debug_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n---- {datetime.utcnow().isoformat()}Z OLLAMA EVAL REQUEST ----\n")
                fh.write("PROMPT:\n")
                fh.write(prompt + "\n\n")
                fh.write("PAYLOAD:\n")
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

        response = _post_json(f"{self._endpoint}/api/generate", payload)
        text = cast(str, response.get("response", "")).strip()
        if not text:
            raise LlmAdapterError("Ollama response did not include text content")

        return _assessment_from_json_text(
            text, provider="ollama", model=self._model, answer=answer
        )


class GeminiLlmAdapter:
    def __init__(self, endpoint: str, model: str, api_key: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._api_key = api_key

    def assess_turn(
        self,
        *,
        answer: str,
        competency: Competency,
        role: str,
        doc_type: str,
        grounded_sources: list[RetrievalEvidence],
    ) -> LlmTurnAssessment:
        prompt = _build_evaluation_prompt(
            answer=answer,
            competency=competency,
            role=role,
            doc_type=doc_type,
            grounded_sources=grounded_sources,
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        print("[DEBUG] Gemini payload:\n" + json.dumps(payload, ensure_ascii=False, indent=2))

        url = (
            f"{self._endpoint}/v1beta/models/{self._model}:generateContent"
            f"?key={self._api_key}"
        )
        # Persist the full evaluation prompt/payload for reliable debugging
        try:
            debug_path = Path(os.getcwd()) / "tmp" / "llm_eval_debug.log"
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            with debug_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n---- {datetime.utcnow().isoformat()}Z GEMINI EVAL REQUEST ----\n")
                fh.write("PROMPT:\n")
                fh.write(prompt + "\n\n")
                fh.write("PAYLOAD:\n")
                fh.write(json.dumps(payload) + "\n")
        except Exception:
            pass

        response = _post_json(url, payload)

        candidates = response.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise LlmAdapterError("Gemini response missing candidates")

        text = (
            candidates[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )
        if not isinstance(text, str) or not text:
            raise LlmAdapterError("Gemini response did not include text content")

        return _assessment_from_json_text(
            text, provider="gemini", model=self._model, answer=answer
        )


class AnthropicLlmAdapter:
    def __init__(self, endpoint: str, model: str, api_key: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._api_key = api_key

    def assess_turn(
        self,
        *,
        answer: str,
        competency: Competency,
        role: str,
        doc_type: str,
        grounded_sources: list[RetrievalEvidence],
    ) -> LlmTurnAssessment:
        prompt = _build_evaluation_prompt(
            answer=answer,
            competency=competency,
            role=role,
            doc_type=doc_type,
            grounded_sources=grounded_sources,
        )
        payload = {
            "model": self._model,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        print("[DEBUG] Anthropic payload:\n" + json.dumps(payload, ensure_ascii=False, indent=2))

        response = _post_json(
            f"{self._endpoint}/v1/messages",
            payload,
            api_key=self._api_key,
            extra_headers={"anthropic-version": "2023-06-01"},
        )

        content = response.get("content")
        if not isinstance(content, list) or not content:
            raise LlmAdapterError("Anthropic response missing content")

        text = ""
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                value = item.get("text")
                if isinstance(value, str):
                    text += value
        text = text.strip()
        if not text:
            raise LlmAdapterError("Anthropic response did not include text content")

        return _assessment_from_json_text(
            text, provider="anthropic", model=self._model, answer=answer
        )


def build_llm_adapter_from_environment() -> LlmAdapter | None:
    enabled_raw = os.getenv("AI_INTERVIEWER_LLM_ENABLED", "0")
    enabled = enabled_raw.strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return None

    provider = os.getenv("AI_INTERVIEWER_LLM_PROVIDER", "ollama").strip().lower()
    if provider == "ollama":
        endpoint = os.getenv("AI_INTERVIEWER_OLLAMA_ENDPOINT", "http://127.0.0.1:11434")
        model = os.getenv("AI_INTERVIEWER_OLLAMA_MODEL", "llama3.1")
        return OllamaLlmAdapter(endpoint=endpoint, model=model)

    if provider == "gemini":
        endpoint = os.getenv("AI_INTERVIEWER_GEMINI_ENDPOINT", "https://generativelanguage.googleapis.com")
        model = os.getenv("AI_INTERVIEWER_GEMINI_MODEL", "gemini-1.5-flash")
        api_key = os.getenv("AI_INTERVIEWER_GEMINI_API_KEY", "").strip()
        if not api_key:
            raise LlmAdapterError("AI_INTERVIEWER_GEMINI_API_KEY is required for Gemini provider")
        return GeminiLlmAdapter(endpoint=endpoint, model=model, api_key=api_key)

    if provider == "anthropic":
        endpoint = os.getenv("AI_INTERVIEWER_ANTHROPIC_ENDPOINT", "https://api.anthropic.com")
        model = os.getenv("AI_INTERVIEWER_ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
        api_key = os.getenv("AI_INTERVIEWER_ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise LlmAdapterError("AI_INTERVIEWER_ANTHROPIC_API_KEY is required for Anthropic provider")
        return AnthropicLlmAdapter(endpoint=endpoint, model=model, api_key=api_key)

    raise LlmAdapterError(f"Unsupported LLM provider: {provider}")


def _assessment_from_json_text(
    text: str, provider: str, model: str, answer: str
) -> LlmTurnAssessment:
    payload = _json_payload_from_text(text)
    print("[DEBUG] Evaluation model output (parsed JSON):\n" + json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return _parse_assessment_payload(
        payload=payload, provider=provider, model=model, answer=answer
    )


def _json_payload_from_text(text: str) -> dict[str, Any]:
    normalized_text = text.strip()
    lines = normalized_text.splitlines()
    if len(lines) >= 3 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        fence_language = lines[0].strip()[3:].strip().lower()
        if fence_language in {"", "json"}:
            normalized_text = "\n".join(lines[1:-1]).strip()

    try:
        payload = json.loads(normalized_text)
    except json.JSONDecodeError as exc:
        raise LlmAdapterError("LLM did not return valid JSON") from exc

    if not isinstance(payload, dict):
        raise LlmAdapterError("LLM JSON payload must be an object")

    return payload


def _parse_assessment_payload(
    *,
    payload: dict[str, Any],
    provider: str,
    model: str,
    answer: str,
) -> LlmTurnAssessment:
    score = payload.get("score")
    off_topic = payload.get("off_topic")
    mixed_signal = payload.get("mixed_signal")
    evidence = payload.get("evidence", [])

    if isinstance(score, bool) or not isinstance(score, (float, int)):
        raise LlmAdapterError("LLM score must be a number")

    score_value = float(score)
    if not math.isfinite(score_value) or score_value < 0 or score_value > 1:
        raise LlmAdapterError("LLM score must be between 0 and 1")

    if not isinstance(off_topic, bool):
        raise LlmAdapterError("LLM off_topic must be a boolean")

    if not isinstance(mixed_signal, bool):
        raise LlmAdapterError("LLM mixed_signal must be a boolean")

    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise LlmAdapterError("LLM evidence must be a list of strings")
    if not evidence or any(not item.strip() or item not in answer for item in evidence):
        logger.warning("LLM evidence includes unverified candidate quotations; retaining model assessment")

    return LlmTurnAssessment(
        score=score_value,
        off_topic=off_topic,
        mixed_signal=mixed_signal,
        evidence=list(evidence),
        provider=provider,
        model=model,
    )


def _build_evaluation_prompt(
    *,
    answer: str,
    competency: Competency,
    role: str,
    doc_type: str,
    grounded_sources: list[RetrievalEvidence],
) -> str:
    if not grounded_sources:
        raise LlmAdapterError("Answer evaluation requires retrieved corpus evidence")
    source_context = "\n".join(
        f"[{source.source_id}] ({source.doc_id}) {source.text}" for source in grounded_sources
    )
    prompt = (
        "You are an interviewer evaluator. "
        "Return ONLY JSON object with keys: score (0..1 number), "
        "off_topic (boolean), mixed_signal (boolean), evidence (array of short strings). "
        "Each evidence string must be an exact, contiguous quote from the candidate answer "
        "that supports the score; never cite retrieved text or include commentary. "
        "Base the evaluation only on the retrieved corpus evidence and the candidate answer.\n"
        f"role={role}; doc_type={doc_type}; competency={competency}\n"
        f"retrieved_corpus_evidence:\n{source_context}\n"
        f"answer={answer}"
    )
    print("[DEBUG] LLM evaluation prompt:\n" + prompt)
    return prompt


def _read_http_error_details(exc: error.HTTPError) -> str:
    details = ""
    try:
        if exc.fp is not None:
            body = exc.read().decode("utf-8", errors="replace")
            if body.strip():
                details = body.strip()
                try:
                    parsed = json.loads(details)
                    if isinstance(parsed, dict):
                        err = parsed.get("error")
                        if isinstance(err, dict):
                            msg = err.get("message")
                            if isinstance(msg, str) and msg:
                                details = msg
                                return details
                        if "message" in parsed:
                            msg = parsed.get("message")
                            if isinstance(msg, str) and msg:
                                details = msg
                                return details
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    return details


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)
    req = request.Request(
        url=url,
        data=data,
        headers=headers,
        method="POST",
    )
    print("[DEBUG] Final HTTP request payload:\n" + json.dumps(payload, ensure_ascii=False, indent=2))
    print("[DEBUG] Final HTTP request URL:\n" + url.split("?", maxsplit=1)[0])

    try:
        with request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        details = _read_http_error_details(exc)
        message = f"LLM provider request failed: HTTP {exc.code}: {exc.reason}"
        if details:
            message = f"{message} - {details}"
        raise LlmAdapterError(message) from exc
    except TimeoutError as exc:
        raise LlmAdapterError("LLM provider request timed out") from exc
    except error.URLError as exc:
        raise LlmAdapterError(f"LLM provider request failed: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LlmAdapterError("LLM provider returned non-JSON response") from exc

    if not isinstance(parsed, dict):
        raise LlmAdapterError("LLM provider response must be a JSON object")

    print("[DEBUG] Evaluation provider raw response:\n" + json.dumps(parsed, ensure_ascii=False, indent=2), flush=True)
    return parsed
