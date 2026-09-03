"""Mask protected content before it leaves AgentGate.

An LLM Judge sends case material to an external provider. In a lending context
that material routinely contains national ID numbers, bank card numbers, phone
numbers, and credentials. Redaction is therefore a required stage on the judge
input path, not a configurable option: `EvaluationContext` defaults to a real
redactor so that "not configured" can never mean "disabled".

Redaction preserves *shape* and destroys *value*. A judge still sees that a
field existed and what kind of thing it held, which is what it needs to reason
about completeness and policy compliance, but it never sees the subject's data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from agentgate.domain import FrozenJsonObject, Trace

#: Field names whose value is masked wholesale, whatever it looks like.
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "api_key", "apikey", "authorization", "access_token", "bank_account",
    "bank_card", "card_no", "card_number", "credential", "credit_card", "email",
    "id_card", "id_number", "id_no", "identity_card", "mobile", "passport",
    "password", "phone", "phone_number", "refresh_token", "secret", "ssn",
    "tax_id", "token",
})

#: Ordered most specific first: an 18-digit national ID also matches the bank
#: card pattern, so it has to be classified before the broader rule sees it.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("secret", re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[=:]\s*\S+"
    )),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("bank_card", re.compile(r"(?<!\d)\d{13,19}(?!\d)")),
)


def placeholder(label: str) -> str:
    return f"[REDACTED:{label}]"


@runtime_checkable
class Redactor(Protocol):
    def redact_value(self, value: Any) -> Any: ...

    def redact_trace(self, trace: Trace) -> Trace: ...


class DefaultRedactor:
    """Key-aware and pattern-based masking for JSON-shaped material."""

    def __init__(
        self,
        sensitive_keys: frozenset[str] = SENSITIVE_KEYS,
        patterns: tuple[tuple[str, re.Pattern[str]], ...] = PATTERNS,
    ) -> None:
        self.sensitive_keys = sensitive_keys
        self.patterns = patterns

    def redact_text(self, text: str) -> str:
        for label, pattern in self.patterns:
            text = pattern.sub(placeholder(label), text)
        return text

    def sensitive_key(self, key: str) -> str | None:
        """Match a sensitive name anywhere inside a field name.

        Real payloads name fields `applicant_phone` and `customerIdCard`, not
        `phone` and `id_card`, so exact matching leaks almost everything. Terms
        are matched as whole word sequences: `tokenizer` is not a `token`.
        """
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
        tokens = [item for item in re.split(r"[_\-\s]+", spaced.lower()) if item]
        for sensitive in self.sensitive_keys:
            want = sensitive.split("_")
            span = len(want)
            if any(tokens[i:i + span] == want for i in range(len(tokens) - span + 1)):
                return sensitive
        return None

    def redact_value(self, value: Any, key: str | None = None) -> Any:
        if key is not None and (sensitive := self.sensitive_key(key)):
            return placeholder(sensitive)
        if isinstance(value, Mapping):
            return {
                str(name): self.redact_value(item, str(name))
                for name, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.redact_value(item) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # A card or phone number stored as a number is still a card or phone
            # number. Only the long, highly specific numeric patterns can match,
            # so ordinary amounts and counts pass through untouched.
            masked = self.redact_text(str(value))
            return masked if masked != str(value) else value
        return value

    def _object(self, value: FrozenJsonObject) -> FrozenJsonObject:
        return FrozenJsonObject(self.redact_value(value))

    def redact_trace(self, trace: Trace) -> Trace:
        """Mask every value-bearing field while keeping the trace navigable.

        Span ids, names, kinds, sequences, and timings survive untouched: they
        are how a Result points at its evidence, and they carry no subject data.
        """
        return trace.model_copy(update={
            "spans": tuple(
                span.model_copy(update={"attributes": self._object(span.attributes)})
                for span in trace.spans
            ),
            "turns": tuple(
                turn.model_copy(update={
                    "input": self._object(turn.input),
                    "output": self._object(turn.output),
                    "state": self._object(turn.state),
                })
                for turn in trace.turns
            ),
            "final_output": self._object(trace.final_output),
            "final_state": self._object(trace.final_state),
        })


__all__ = ["PATTERNS", "SENSITIVE_KEYS", "DefaultRedactor", "Redactor", "placeholder"]
