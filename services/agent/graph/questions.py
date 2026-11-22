from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib import error, request

from services.agent.graph.models import Competency, InterviewGraphState

MODEL_OVERLOADED_MESSAGE = (
    "El sistema o el modelo está saturado en este momento. Intenta nuevamente más tarde."
)


class QuestionGeneratorError(RuntimeError):
    pass


class QuestionGenerator(Protocol):
    def generate_question(self, state: InterviewGraphState) -> str:
        ...


@dataclass(frozen=True)
class DeterministicQuestionGenerator:
    def generate_question(self, state: InterviewGraphState) -> str:
        return deterministic_question_for_state(state)


class GitHubModelsQuestionGenerator:
    def __init__(self, token: str, model: str) -> None:
        self._token = token
        self._model = model
        self._endpoint = "https://models.inference.ai.azure.com"

    def generate_question(self, state: InterviewGraphState) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": _build_question_prompt(state)}],
            "temperature": 0.4,
        }
        url = f"{self._endpoint}/chat/completions"
        response = _post_json(url, payload, extra_headers={"Authorization": f"Bearer {self._token}"})

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise QuestionGeneratorError("GitHub Models question response missing choices")

        text = choices[0].get("message", {}).get("content", "").strip()
        if not isinstance(text, str) or not text:
            raise QuestionGeneratorError("GitHub Models question response did not include text")

        question = _sanitize_question(text)
        if not question:
            raise QuestionGeneratorError("GitHub Models returned empty question")

        return question


class OllamaQuestionGenerator:
    def __init__(self, endpoint: str, model: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model

    def generate_question(self, state: InterviewGraphState) -> str:
        prompt = _build_question_prompt(state)
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.4},
        }
        print(
            "[DEBUG] Ollama question payload:\n"
            + json.dumps(payload, ensure_ascii=False, indent=2),
            flush=True,
        )
        response = _post_json(f"{self._endpoint}/api/generate", payload)

        text = str(response.get("response", "")).strip()
        if not text:
            raise QuestionGeneratorError("Ollama question response did not include text")

        question = _sanitize_question(text)
        if not question:
            raise QuestionGeneratorError("Ollama returned empty question")

        return question


class GeminiQuestionGenerator:
    def __init__(self, endpoint: str, model: str, api_key: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._api_key = api_key

    def generate_question(self, state: InterviewGraphState) -> str:
        prompt = _build_question_prompt(state)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4},
        }
        url = (
            f"{self._endpoint}/v1beta/models/{self._model}:generateContent"
            f"?key={self._api_key}"
        )
        print(f"[DEBUG] Gemini POST body: {json.dumps(payload, ensure_ascii=False)}")
        try:
            logger = logging.getLogger(__name__)
            redacted_url = url.split("?")[0]
            logger.debug("Calling Gemini endpoint %s with payload: %s", redacted_url, json.dumps(payload))
            try:
                print(f"[DEBUG] Calling Gemini endpoint {redacted_url} with payload: {json.dumps(payload)}")
            except Exception:
                pass
        except Exception:
            pass

        try:
            debug_path = Path(os.getcwd()) / "tmp" / "llm_debug.log"
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            with debug_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n---- {datetime.utcnow().isoformat()}Z GEMINI REQUEST ----\n")
                fh.write("PROMPT:\n")
                fh.write(prompt + "\n\n")
                fh.write("PAYLOAD:\n")
                fh.write(json.dumps(payload) + "\n")
        except Exception:
            pass

        response = _post_json(url, payload)

        candidates = response.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise QuestionGeneratorError("Gemini question response missing candidates")

        parts = candidates[0].get("content", {}).get("parts", [])
        if not isinstance(parts, list) or not parts:
            raise QuestionGeneratorError("Gemini question response missing parts")

        text = ""
        for part in parts:
            if isinstance(part, dict):
                value = part.get("text")
                if isinstance(value, str):
                    text += value

        text = text.strip()
        if not text:
            raise QuestionGeneratorError("Gemini question response did not include text")

        # If the model returned an explanatory paragraph instead of a single
        # question, try to synthesize a contextual question locally rather
        # than falling back to the generic deterministic question.
        if "?" not in text:
            # Construct a minimal contextual question using competency and role
            fallback_q = f"What is your approach to {state.current_competency} for the role {state.role}?"
            question = _sanitize_question(fallback_q)
            if not question:
                raise QuestionGeneratorError("Gemini returned explanatory text and fallback synthesis failed")
            return question

        question = _sanitize_question(text)
        if not question:
            raise QuestionGeneratorError("Gemini returned empty question after sanitization")

        return question


class AnthropicQuestionGenerator:
    def __init__(self, endpoint: str, model: str, api_key: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._api_key = api_key

    def generate_question(self, state: InterviewGraphState) -> str:
        payload = {
            "model": self._model,
            "max_tokens": 128,
            "messages": [{"role": "user", "content": _build_question_prompt(state)}],
            "temperature": 0.4,
        }
        response = _post_json(
            f"{self._endpoint}/v1/messages",
            payload,
            api_key=self._api_key,
            extra_headers={"anthropic-version": "2023-06-01"},
        )

        content = response.get("content")
        if not isinstance(content, list) or not content:
            raise QuestionGeneratorError("Anthropic question response missing content")

        text = ""
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                value = item.get("text")
                if isinstance(value, str):
                    text += value
        text = text.strip()
        if not text:
            raise QuestionGeneratorError("Anthropic returned empty question")

        question = _sanitize_question(text)
        if not question:
            raise QuestionGeneratorError("Anthropic returned empty question")
        return question


def build_question_generator_from_environment() -> QuestionGenerator:
    logger = logging.getLogger(__name__)
    enabled_raw = os.getenv("AI_INTERVIEWER_QUESTION_LLM_ENABLED", "0")
    enabled = enabled_raw.strip().lower() in {"1", "true", "yes", "on"}
    provider = os.getenv("AI_INTERVIEWER_QUESTION_LLM_PROVIDER", "gemini").strip().lower()
    logger.debug("LLM enabled=%s provider=%s (raw=%s)", enabled, provider, enabled_raw)
    try:
        print(f"[DEBUG] build_question_generator_from_environment: enabled={enabled} provider={provider} raw={enabled_raw}")
    except Exception:
        pass
    # Auto-enable LLM if an API key is present but enabled flag was not set
    try:
        gemini_key_present = bool(os.getenv("AI_INTERVIEWER_QUESTION_GEMINI_API_KEY") or os.getenv("AI_INTERVIEWER_GEMINI_API_KEY"))
        if not enabled and gemini_key_present and provider == "gemini":
            enabled = True
            logger.debug("Auto-enabled LLM because Gemini API key was present")
            try:
                print("[DEBUG] Auto-enabled LLM because Gemini API key was present")
            except Exception:
                pass
    except Exception:
        gemini_key_present = False

    # Also persist environment debug info to a file for reliable capture
    try:
        debug_path = Path(os.getcwd()) / "tmp" / "llm_debug.log"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        with debug_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n---- {datetime.utcnow().isoformat()}Z BUILD_GENERATOR ----\n")
            fh.write(f"enabled={enabled} provider={provider} enabled_raw={enabled_raw}\n")
            fh.write(f"AI_INTERVIEWER_QUESTION_GEMINI_API_KEY present={bool(os.getenv('AI_INTERVIEWER_QUESTION_GEMINI_API_KEY'))}\n")
    except Exception:
        pass
    if not enabled:
        return DeterministicQuestionGenerator()

    # provider variable already read above in debug log path

    if provider == "ollama":
        endpoint = os.getenv(
            "AI_INTERVIEWER_QUESTION_OLLAMA_ENDPOINT",
            os.getenv("AI_INTERVIEWER_OLLAMA_ENDPOINT", "http://127.0.0.1:11434"),
        )
        model = os.getenv(
            "AI_INTERVIEWER_QUESTION_OLLAMA_MODEL",
            os.getenv("AI_INTERVIEWER_OLLAMA_MODEL", "llama3.1"),
        )
        return OllamaQuestionGenerator(endpoint=endpoint, model=model)

    if provider == "github_models":
        token = os.getenv("AI_INTERVIEWER_QUESTION_GITHUB_TOKEN", "").strip()
        if not token:
            raise QuestionGeneratorError("AI_INTERVIEWER_QUESTION_GITHUB_TOKEN is required")
        model = os.getenv("AI_INTERVIEWER_QUESTION_GITHUB_MODEL", "gpt-4o-mini")
        return GitHubModelsQuestionGenerator(token=token, model=model)

    if provider == "gemini":
        endpoint = os.getenv(
            "AI_INTERVIEWER_QUESTION_GEMINI_ENDPOINT",
            os.getenv("AI_INTERVIEWER_GEMINI_ENDPOINT", "https://generativelanguage.googleapis.com"),
        )
        model = os.getenv(
            "AI_INTERVIEWER_QUESTION_GEMINI_MODEL",
            os.getenv("AI_INTERVIEWER_GEMINI_MODEL", "gemini-1.5-flash"),
        )
        api_key = os.getenv("AI_INTERVIEWER_QUESTION_GEMINI_API_KEY", "").strip() or os.getenv(
            "AI_INTERVIEWER_GEMINI_API_KEY", ""
        ).strip()
        if not api_key:
            raise QuestionGeneratorError(
                "AI_INTERVIEWER_QUESTION_GEMINI_API_KEY or AI_INTERVIEWER_GEMINI_API_KEY is required"
            )
        return GeminiQuestionGenerator(endpoint=endpoint, model=model, api_key=api_key)

    if provider == "anthropic":
        endpoint = os.getenv(
            "AI_INTERVIEWER_QUESTION_ANTHROPIC_ENDPOINT",
            os.getenv("AI_INTERVIEWER_ANTHROPIC_ENDPOINT", "https://api.anthropic.com"),
        )
        model = os.getenv(
            "AI_INTERVIEWER_QUESTION_ANTHROPIC_MODEL",
            os.getenv("AI_INTERVIEWER_ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
        )
        api_key = os.getenv("AI_INTERVIEWER_QUESTION_ANTHROPIC_API_KEY", "").strip() or os.getenv(
            "AI_INTERVIEWER_ANTHROPIC_API_KEY", ""
        ).strip()
        if not api_key:
            raise QuestionGeneratorError(
                "AI_INTERVIEWER_QUESTION_ANTHROPIC_API_KEY or AI_INTERVIEWER_ANTHROPIC_API_KEY is required"
            )
        return AnthropicQuestionGenerator(endpoint=endpoint, model=model, api_key=api_key)

    raise QuestionGeneratorError(f"Unsupported question provider: {provider}")


def deterministic_question_for_competency(competency: Competency) -> str:
    return _deterministic_sequence_for_competency(competency)[0]


def deterministic_question_for_state(state: InterviewGraphState) -> str:
    sequence = _deterministic_sequence_for_competency(state.current_competency)
    index = min(state.turn_index, len(sequence) - 1)
    return sequence[index]


def _deterministic_sequence_for_competency(competency: Competency) -> list[str]:
    prompts = {
        "debugging": [
            "Question 1.",
            "Question 2",
            "When an agent repeatedly calls a tool without reaching a terminal state, how do you add tracing, timeout, and recovery guardrails?",
        ],
        "api_design": [
            "How do you keep API versions backward compatible?",
            "How do you design a versioned API that supports gradual migration without breaking clients?",
            "How do you evolve an API contract while keeping compatibility, observability, and deprecation safe?",
        ],
        "test_reliability": [
            "How do you improve CI test reliability?",
            "What patterns do you use to make flaky tests reproducible and diagnosable in CI?",
            "How do you build a resilient test strategy that catches regressions without masking real failures?",
        ],
    }
    return prompts[competency]


def _build_question_prompt(state: InterviewGraphState) -> str:
    role_context = getattr(state, "role_description", "").strip() or "No explicit job description provided."
    difficulty = state.difficulty_label
    question_style = {
        "low": "keep it concrete, short, and focused on fundamentals",
        "medium": "keep it practical and moderately technical",
        "high": "make it deeper, scenario-based, and more nuanced",
    }[difficulty]
    prompt = (
        "You are an AI interviewer. Return exactly one interview question as plain text. "
        "Do not return JSON, bullets, labels, or explanations. Return only the question, ending with a question mark '?'. Keep it under 120 characters. "
        "The question must target the competency and the role context.\n"
        f"role={state.role}; doc_type={state.doc_type}; competency={state.current_competency}; "
        f"role_description={role_context}; turn_index={state.turn_index}; max_turns={state.max_turns}; "
        f"difficulty={difficulty}; style={question_style}; "
        f"remaining_competencies={state.remaining_competencies}"
    )
    print("[DEBUG] Question prompt:\n" + prompt, flush=True)
    return prompt


def _sanitize_question(raw: str) -> str:
    print("[DEBUG] Question model raw text:\n" + raw, flush=True)
    first_line = raw.strip().splitlines()[0].strip()
    print(f"[DEBUG] Question after sanitize: {first_line}", flush=True)
    if first_line.startswith("{") and first_line.endswith("}"):
        return ""
    return first_line


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
    max_retries: int = 2,
) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    for attempt in range(max_retries + 1):
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=url,
            data=data,
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=180) as response:
                body = response.read().decode("utf-8")
                try:
                    logger.debug("Question provider response from %s: %s", url.split("?")[0], body)
                except Exception:
                    pass
                try:
                    print(f"[DEBUG] Question provider response from {url.split('?')[0]}: {body}")
                except Exception:
                    pass
        except error.HTTPError as exc:
            details = _read_http_error_details(exc)
            if exc.code in {429, 500, 502, 503, 504} and attempt < max_retries:
                print(
                    f"[WARN] Transient provider error on attempt {attempt + 1}/{max_retries + 1}: "
                    f"HTTP {exc.code} - {details or exc.reason}. Retrying..."
                )
                continue
            message = f"Question provider request failed: HTTP {exc.code}: {exc.reason}"
            if details:
                message = f"{message} - {details}"
            raise QuestionGeneratorError(message) from exc
        except error.URLError as exc:
            if attempt < max_retries:
                print(f"[WARN] Transient provider error on attempt {attempt + 1}/{max_retries + 1}: {exc}. Retrying...")
                continue
            raise QuestionGeneratorError(f"Question provider request failed: {exc}") from exc
        except OSError as exc:
            if attempt < max_retries:
                print(f"[WARN] Transient network error on attempt {attempt + 1}/{max_retries + 1}: {exc}. Retrying...")
                continue
            raise QuestionGeneratorError(f"Question provider request failed: {exc}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise QuestionGeneratorError("Question provider returned non-JSON response") from exc

        if not isinstance(parsed, dict):
            raise QuestionGeneratorError("Question provider response must be a JSON object")

        return parsed

    raise QuestionGeneratorError("Question provider request failed after retries")
