"""Deterministic in-process judge model for tests, demos, and offline runs.

This is not a convenience: it is what keeps the judge path testable and keeps
`EvaluationService` startable with no endpoint and no credential, which the demo
depends on today. Every J2 and J3 test drives the judge through this double, so
judge behaviour is asserted without a network, a key, or a bill.

It records every request it receives, so tests can prove what was actually sent
to a model -- above all that redaction ran before the trace left the process.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agentgate.domain.base import content_sha256
from agentgate.evaluator.judge import (
    JudgeModelError, JudgeModelUnavailable, JudgeRequest, JudgeResponse,
)

Scripted = str | BaseException
Responder = Callable[[JudgeRequest], Scripted]


def request_fingerprint(request: JudgeRequest) -> str:
    """Stable digest of request content, used for deterministic fake request IDs."""
    return content_sha256({
        "model": request.model,
        "system": request.system,
        "user": request.user,
        "temperature": request.temperature,
        "seed": request.seed,
        "max_output_tokens": request.max_output_tokens,
        "response_format": request.response_format,
        "extra": request.extra,
    })


class FakeJudgeModel:
    """Answer judge completions from a script instead of a provider.

    `responses` accepts:

    - a `str`, replayed for every call;
    - a `BaseException`, raised on every call;
    - a sequence of either, consumed in order and exhausted deliberately;
    - a callable receiving the `JudgeRequest` and returning either.
    """

    provider = "fake"

    def __init__(
        self,
        responses: Scripted | Sequence[Scripted] | Responder = "",
        model: str = "fake-judge-1",
        finish_reason: str = "stop",
        latency_ms: float = 0.0,
    ) -> None:
        self.model = model
        self.finish_reason = finish_reason
        self.latency_ms = latency_ms
        self.requests: list[JudgeRequest] = []
        self._script: list[Scripted] | None = None
        self._responder: Responder | None = None
        self._constant: Scripted | None = None

        if callable(responses) and not isinstance(responses, BaseException):
            self._responder = responses
        elif isinstance(responses, (str, BaseException)):
            self._constant = responses
        else:
            self._script = list(responses)

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def last_request(self) -> JudgeRequest | None:
        return self.requests[-1] if self.requests else None

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        self.requests.append(request)
        scripted = self._next(request)
        if isinstance(scripted, BaseException):
            raise scripted
        return JudgeResponse(
            text=scripted,
            resolved_model=self.model,
            request_id=f"fake-{request_fingerprint(request)[:16]}",
            # Deterministic stand-ins, so evidence plumbing can be asserted.
            input_tokens=len(request.user) // 4,
            output_tokens=len(scripted) // 4,
            latency_ms=self.latency_ms,
            finish_reason=self.finish_reason,
        )

    def _next(self, request: JudgeRequest) -> Scripted:
        if self._responder is not None:
            return self._responder(request)
        if self._constant is not None:
            return self._constant
        assert self._script is not None
        if not self._script:
            raise JudgeModelUnavailable(
                "FakeJudgeModel script is exhausted; the test asked for more "
                "completions than it scripted"
            )
        return self._script.pop(0)


def always_fail(error: JudgeModelError) -> FakeJudgeModel:
    """A judge model that raises `error` on every call."""
    return FakeJudgeModel(responses=error)
