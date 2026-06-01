"""Shared thin HTTP client for the local Ollama daemon (spec 0003 §4.0).

The single seam to Ollama — reused by both :class:`OllamaBackend` (Stage 3) and ``tools/ask.py``
(NL→Cypher) so host errors and timeouts are handled in exactly one place. Always
``stream:false``; honors ``keep_alive`` to hold the model warm across a run.
"""
from __future__ import annotations

import os

_DEFAULT_HOST = "http://localhost:11434"
_DEFAULT_KEEP_ALIVE = "10m"
_DEFAULT_TIMEOUT_S = 120.0


class OllamaError(RuntimeError):
    """Raised on an unreachable host or a non-2xx response (clear, actionable message)."""


class OllamaClient:
    def __init__(
        self,
        host: str | None = None,
        keep_alive: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.host = (host or os.environ.get("OLLAMA_HOST", _DEFAULT_HOST)).rstrip("/")
        self.keep_alive = keep_alive or os.environ.get("OLLAMA_KEEP_ALIVE", _DEFAULT_KEEP_ALIVE)
        self.timeout_s = (
            timeout_s
            if timeout_s is not None
            else float(os.environ.get("OLLAMA_TIMEOUT_S", _DEFAULT_TIMEOUT_S))
        )

    def _post(self, path: str, payload: dict) -> dict:
        import httpx

        url = f"{self.host}{path}"
        try:
            resp = httpx.post(url, json=payload, timeout=self.timeout_s)
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Failed to reach Ollama at {self.host} — is the daemon running "
                f"(`ollama serve`)? Underlying error: {exc}"
            ) from exc
        if resp.status_code >= 300:
            body = resp.text[:500]
            raise OllamaError(
                f"Ollama returned HTTP {resp.status_code} for {path}: {body}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise OllamaError(f"Ollama returned a non-JSON body for {path}: {resp.text[:500]}") from exc

    def chat(
        self,
        model: str,
        messages: list[dict],
        *,
        options: dict | None = None,
        fmt: str | dict | None = None,
    ) -> str:
        """POST /api/chat (stream:false). Returns the assistant message content string.

        *fmt* maps to Ollama's ``format`` (``"json"`` or a JSON schema) for structured output.
        """
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
        }
        if options:
            payload["options"] = options
        if fmt is not None:
            payload["format"] = fmt
        data = self._post("/api/chat", payload)
        return (data.get("message") or {}).get("content", "")

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        options: dict | None = None,
        fmt: str | dict | None = None,
    ) -> str:
        """POST /api/generate (stream:false). Returns the ``response`` string."""
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
        }
        if system is not None:
            payload["system"] = system
        if options:
            payload["options"] = options
        if fmt is not None:
            payload["format"] = fmt
        data = self._post("/api/generate", payload)
        return data.get("response", "")
