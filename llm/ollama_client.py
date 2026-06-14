"""Transport client for Ollama JSON generation requests.

The router uses this client as the fast path for structured completions. The
client does not make routing decisions; it posts the prompt, requests JSON,
and normalizes the response body into a dictionary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

try:  # pragma: no cover - exercised indirectly when httpx is installed
    import httpx
except ModuleNotFoundError:  # pragma: no cover - keeps unit tests importable without the SDK
    class _HTTPXFallback:
        """Minimal stand-in that preserves the import surface used in tests."""

        class ConnectError(Exception):
            """Raised when the host cannot be reached."""

        class HTTPError(Exception):
            """Raised when a request cannot be completed."""

        class Client:
            """Fallback client that raises if a real HTTP call is attempted."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise ModuleNotFoundError("httpx is not installed")

    httpx = _HTTPXFallback()  # type: ignore[assignment]

from core.exceptions import OllamaUnavailableError


class OllamaClient:
    """Call the Ollama generate endpoint for a single completion."""

    def __init__(self, settings: Any, timeout: float = 60.0) -> None:
        """Store the runtime settings and transport timeout."""

        self.settings = settings
        self.timeout = timeout

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Mapping[str, Any] | None = None,
        max_tokens: int = 1000,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send the prompt to Ollama and return the parsed JSON response."""

        prompt = self._compose_prompt(system_prompt, user_prompt, response_schema)
        payload = {
            "model": model or getattr(self.settings, "OLLAMA_MODEL", "gemma4:e4b"),
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": max_tokens},
        }

        url = f"{getattr(self.settings, 'OLLAMA_HOST', 'http://localhost:11434').rstrip('/')}/api/generate"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(f"Unable to reach Ollama at {url}") from exc

        return self._parse_response(response.json())

    def _compose_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Mapping[str, Any] | None,
    ) -> str:
        """Combine the system and user prompts and optionally append schema guidance."""

        pieces = ["System prompt:", system_prompt.strip(), "", "User prompt:", user_prompt.strip()]
        if response_schema:
            pieces.extend([
                "",
                "Return only valid JSON that matches this schema:",
                json.dumps(dict(response_schema), indent=2, sort_keys=True),
            ])
        return "\n".join(pieces).strip()

    def _parse_response(self, payload: Any) -> dict[str, Any]:
        """Normalize common Ollama response shapes into a dictionary."""

        if isinstance(payload, dict):
            if isinstance(payload.get("response"), str):
                text = payload["response"].strip()
                if text:
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        payload = dict(payload)
                        payload["response"] = text
                    else:
                        if isinstance(parsed, dict):
                            return parsed
                        return {"response": parsed}
            return payload

        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return {"response": payload}
            if isinstance(parsed, dict):
                return parsed
            return {"response": parsed}

        return {"response": payload}


__all__ = ["OllamaClient"]