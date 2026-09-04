"""OpenAI-compatible chat-completions adapter for Judge model access.

This is the Judge's model path and is intentionally separate from
`demo/provider.py`, which drives the *target* agent. Sharing one call path
between the system under test and the system judging it would let a single
provider outage, credential, or configuration mistake corrupt both sides of an
evaluation at once.

Scope is transport only: HTTP, authentication, retry, timeout, and token
accounting. Prompt construction and verdict interpretation live in
`evaluator/judge/`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from agentgate.evaluator.judge import (
    JudgeModelInvalidResponse, JudgeModelTimeout, JudgeModelUnavailable, JudgeRequest,
    JudgeResponse,
)

from .credentials import CredentialResolver, EnvCredentialResolver

#: Statuses worth another attempt: rate limiting and server-side faults.
RETRYABLE_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})


def _is_timeout(error: BaseException) -> bool:
    reason = getattr(error, "reason", None)
    return isinstance(error, TimeoutError) or isinstance(reason, TimeoutError)


class OpenAICompatibleJudgeModel:
    """Call any OpenAI-compatible `/chat/completions` endpoint as a Judge model."""

    provider = "openai_compatible"

    def __init__(
        self,
        endpoint: str,
        credential_ref: str | None = None,
        resolver: CredentialResolver | None = None,
        api_key: str | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        sleep=time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if credential_ref and api_key:
            raise ValueError("provide either credential_ref or api_key, not both")
        self.endpoint = endpoint
        self.credential_ref = credential_ref
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        # Resolved once so a missing secret fails at composition time rather than
        # mid-Run. Stored privately and kept out of __repr__.
        self._api_key = api_key or (
            (resolver or EnvCredentialResolver()).resolve(credential_ref)
            if credential_ref else None
        )

    def __repr__(self) -> str:
        """Never render the resolved secret."""
        return (
            f"OpenAICompatibleJudgeModel(endpoint={self.endpoint!r}, "
            f"credential_ref={self.credential_ref!r})"
        )

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        body = json.dumps(self._payload(request)).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                http_request = urllib.request.Request(
                    self.endpoint, data=body, headers=headers, method="POST"
                )
                with urllib.request.urlopen(
                    http_request, timeout=request.timeout_seconds
                ) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as exc:
                last_error = JudgeModelUnavailable(
                    f"judge provider returned HTTP {exc.code}"
                )
                if exc.code not in RETRYABLE_STATUSES:
                    raise last_error from None
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = (
                    JudgeModelTimeout(
                        f"judge provider exceeded {request.timeout_seconds}s"
                    )
                    if _is_timeout(exc)
                    else JudgeModelUnavailable("judge provider is unreachable")
                )
            except json.JSONDecodeError:
                # A syntactically broken body will not become valid on retry.
                raise JudgeModelInvalidResponse(
                    "judge provider returned a non-JSON body"
                ) from None
            else:
                latency_ms = (time.monotonic() - started) * 1000
                return self._parse(payload, request, latency_ms, attempt)

            if attempt < self.max_attempts:
                self._sleep(self.backoff_seconds * attempt)

        raise last_error if last_error else JudgeModelUnavailable("judge provider failed")

    def _payload(self, request: JudgeRequest) -> dict[str, Any]:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.user})
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            # Always sent explicitly: an omitted temperature silently becomes the
            # provider default of 1.0, which makes judging non-reproducible.
            "temperature": request.temperature,
        }
        if request.seed is not None:
            payload["seed"] = request.seed
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        payload.update(request.extra)
        return payload

    def _parse(
        self, payload: Any, request: JudgeRequest, latency_ms: float, attempt: int
    ) -> JudgeResponse:
        try:
            choice = payload["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise JudgeModelInvalidResponse(
                "judge provider returned no completion choice"
            ) from None
        if not isinstance(text, str):
            raise JudgeModelInvalidResponse(
                "judge provider returned a completion without text content"
            )
        usage = payload.get("usage") or {}
        return JudgeResponse(
            text=text,
            resolved_model=payload.get("model") or request.model,
            request_id=payload.get("id"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
            attempt_count=attempt,
        )
