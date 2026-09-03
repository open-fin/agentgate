"""Internal judge-model contract implemented by `integrations/model_providers/`.

This mirrors how `run/target_protocol.py` relates to `integrations/targets/`: the
protocol belongs to the capability that consumes it, and every vendor adapter
translates its own API into this shape. The protocol is deliberately transport
shaped. It knows about messages, generation settings, and token accounting; it
knows nothing about rubrics, criteria, scores, or verdicts, which stay in
`evaluator/judge/`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from agentgate.domain.base import content_sha256

ResponseFormat = Literal["text", "json_object"]


class JudgeModelError(Exception):
    """Base class for every judge-model transport failure."""


class JudgeModelTimeout(JudgeModelError, TimeoutError):
    """The provider did not answer within the request deadline.

    Subclassing TimeoutError makes `evaluator/runner.py` record this as a
    retryable `timeout` error category rather than an opaque crash.
    """


class JudgeModelInvalidResponse(JudgeModelError, ValueError):
    """The provider answered, but not with a usable completion envelope.

    Subclassing ValueError maps this to the `invalid_output` error category.
    This covers the transport envelope only. A judge whose *content* fails the
    verdict contract is diagnosed in `evaluator/judge/`, not here.
    """


class JudgeModelUnavailable(JudgeModelError):
    """The provider could not be reached, refused the call, or gave up."""


class CredentialUnavailable(JudgeModelError):
    """A configured `credential_ref` could not be resolved to a secret."""


@dataclass(frozen=True)
class JudgeRequest:
    """One completion request. Never carries a secret.

    Credentials belong to the client, not the request, so a request can be
    logged, hashed for caching, or asserted on in tests without leaking a key.
    """

    model: str
    user: str
    system: str | None = None
    temperature: float = 0.0
    seed: int | None = None
    max_output_tokens: int | None = None
    response_format: ResponseFormat = "text"
    timeout_seconds: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)


def request_fingerprint(request: JudgeRequest) -> str:
    """Stable digest of request content for safe correlation and test doubles.

    `timeout_seconds` is excluded: waiting longer does not change the semantic
    request content.
    """
    payload = asdict(request)
    payload.pop("timeout_seconds", None)
    return content_sha256(payload)


@dataclass(frozen=True)
class JudgeResponse:
    """One completion result plus the accounting a Run must be able to audit."""

    text: str
    resolved_model: str
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    finish_reason: str | None = None
    attempt_count: int = 1

    @property
    def truncated(self) -> bool:
        """Whether the provider stopped on the output-token limit."""
        return self.finish_reason == "length"


@runtime_checkable
class CredentialChecker(Protocol):
    """Proves a `credential_ref` resolves without reading its value.

    Declared by the consumer so pre-run validation can reject a misconfigured
    judge before a Run starts, while secret storage itself stays in
    `integrations/model_providers/`.
    """

    def is_available(self, credential_ref: str) -> bool: ...


@runtime_checkable
class JudgeModelClient(Protocol):
    """The only judge-model surface `evaluator/judge/` is allowed to depend on."""

    provider: str

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        """Run one completion, or raise a `JudgeModelError`."""
        ...
