"""LLM provider abstraction — no vendor hard-coded.

``OpenAICompatibleLLM`` works against any ``/chat/completions`` endpoint
(OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL style env vars).
``DeterministicLLM`` is the offline fallback used by DEMO_MODE: it never
pretends to be a model — responses are labelled ``mode="demo"`` end to end.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.core.errors import LLMUnavailableError
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class LLMMessage:
    role: str
    content: str | list[dict[str, Any]]


@dataclass
class LLMResponse:
    text: str
    model: str
    response_id: str = ""
    latency_ms: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    structured: dict[str, Any] | None = None


class LLMProvider(Protocol):
    name: str

    def generate(self, messages: list[LLMMessage], *, json_schema: dict | None = None,
                 temperature: float = 0.0, max_tokens: int = 1200) -> LLMResponse: ...


class OpenAICompatibleLLM:
    name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def generate(self, messages, *, json_schema=None, temperature=0.0, max_tokens=1200) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "ariadne_output", "schema": json_schema, "strict": True},
            }
        last_exc: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                t0 = time.perf_counter()
                with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                    resp = client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                text = data["choices"][0]["message"]["content"]
                return LLMResponse(
                    text=text,
                    model=data.get("model", self.model),
                    response_id=data.get("id", ""),
                    latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                    usage=data.get("usage", {}),
                    structured=_parse_json(text) if json_schema else None,
                )
            except Exception as exc:
                last_exc = exc
                log.warning("llm_attempt_failed", attempt=attempt, error=str(exc))
        raise LLMUnavailableError(f"LLM endpoint '{self.base_url}' unreachable.", detail=str(last_exc))


class DeterministicLLM:
    """Offline fallback.  Returns exactly what the caller seeded; no prose magic."""

    name = "deterministic-demo"

    def generate(self, messages, *, json_schema=None, temperature=0.0, max_tokens=1200) -> LLMResponse:
        last = messages[-1].content if messages else ""
        return LLMResponse(text=last if isinstance(last, str) else json.dumps(last), model=self.name,
                           response_id="demo", latency_ms=0.0)


def _parse_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 < end:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _provider
    if _provider is not None:
        return _provider
    if settings.llm_configured:
        _provider = OpenAICompatibleLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    else:
        _provider = DeterministicLLM()
    return _provider


def reset_provider_cache() -> None:
    global _provider
    _provider = None


def is_live() -> bool:
    return isinstance(get_llm_provider(), OpenAICompatibleLLM)
