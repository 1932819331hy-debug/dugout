"""LLM access: any OpenAI-compatible chat endpoint serving an open-weight model.

Default is a local Ollama (`LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=qwen2.5:3b`). A hosted endpoint
(e.g. OpenRouter's free open-weight models) works the same way with `LLM_API_KEY`. The key is sent only as the
Authorization header of that endpoint and is never logged.

The LLM only ever turns fact cards into prose. It never sees a number (facts carry placeholders, not values),
and its output is rejected unless it passes the same checks as the Stat Auditor.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx

log = logging.getLogger(__name__)


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


class LLMError(RuntimeError):
    pass


class OpenAICompatLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 180.0,
        temperature: float = 0.2,
        max_tokens: int = 400,
    ):
        self.base_url, self.model = base_url.rstrip("/"), model
        self.name = model
        self.temperature, self.max_tokens = temperature, max_tokens
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(timeout=timeout, headers=headers)

    def complete(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "seed": 7,
        }
        try:
            r = self._http.post(f"{self.base_url}/chat/completions", json=body)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"{self.model}: {type(exc).__name__}") from exc  # no URL/headers in the message


@dataclass
class ScriptedLLM:
    """Deterministic stand-in for tests: replies from a list (or a function of the prompt)."""

    replies: list[str] | Callable[[str, str], str] = field(default_factory=list)
    name: str = "scripted"
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if callable(self.replies):
            return self.replies(system, user)
        if not self.replies:
            raise LLMError("script exhausted")
        return self.replies.pop(0)


def from_settings() -> LLM | None:
    """The configured LLM, or None when the endpoint is unreachable (agents then use templates only)."""
    from dugout_pipeline.settings import get_settings

    s = get_settings()
    llm = OpenAICompatLLM(s.llm_base_url, s.llm_model, s.secret("llm_api_key"))
    for attempt in range(2):  # a local server may still be loading its model: be patient once
        try:
            httpx.get(f"{llm.base_url}/models", timeout=30, headers=llm._http.headers).raise_for_status()
            break
        except httpx.HTTPError:
            if attempt:
                log.warning("LLM endpoint not reachable; using deterministic templates only")
                return None
    return llm
