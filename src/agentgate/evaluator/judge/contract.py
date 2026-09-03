"""The judge verdict contract and its strict parser.

A judge answers in JSON, not prose: structured output is what makes a verdict
parseable and comparable across samples. Anything the model returns
that does not satisfy this contract is a judge *malfunction*, so it raises and
becomes an ERROR Result. It is never silently read as the agent failing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agentgate.domain import ScoreScale

#: Public reason text is bounded; a judge must not be able to inflate a Result.
MAX_REASON_CHARS = 600
MAX_VIOLATIONS = 20

PASS = "pass"
FAIL = "fail"
UNCERTAIN = "uncertain"
VERDICTS = (PASS, FAIL, UNCERTAIN)


class JudgeContractError(ValueError):
    """The judge answered, but not in the required shape.

    Subclasses ValueError so `evaluator/runner.py` records it as
    `invalid_output` -- an evaluator error, not an agent failure.
    """


@dataclass(frozen=True)
class Violation:
    criterion: str
    detail: str


@dataclass(frozen=True)
class Verdict:
    """One parsed judgement, with its score already normalized to 0..1."""

    verdict: str
    score: float
    confidence: float
    reason: str
    violations: tuple[Violation, ...] = ()

    @property
    def passed(self) -> bool:
        return self.verdict == PASS


def response_instructions(scale: ScoreScale) -> str:
    """The output contract, rendered into the judge prompt verbatim."""
    return (
        "Answer with a single JSON object and nothing else:\n"
        '{\n'
        f'  "verdict": one of {list(VERDICTS)},\n'
        f'  "score": a number from {scale.minimum} to {scale.maximum},\n'
        '  "confidence": a number from 0 to 1 expressing how sure you are,\n'
        '  "reason": one short sentence justifying the verdict,\n'
        '  "violations": [{"criterion": "...", "detail": "..."}]\n'
        '}\n'
        'Use "uncertain" when the evidence does not let you decide. '
        'Do not wrap the JSON in code fences or commentary.'
    )


def _number(payload: dict[str, Any], key: str, required: bool, default: float) -> float:
    if key not in payload:
        if required:
            raise JudgeContractError(f"judge response is missing {key!r}")
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JudgeContractError(f"judge response {key!r} is not a number")
    return float(value)


def _violations(payload: dict[str, Any]) -> tuple[Violation, ...]:
    raw = payload.get("violations") or ()
    if isinstance(raw, (str, dict)):
        raise JudgeContractError("judge response 'violations' must be a list")
    collected = []
    for item in list(raw)[:MAX_VIOLATIONS]:
        if not isinstance(item, dict):
            raise JudgeContractError("each violation must be an object")
        collected.append(Violation(
            criterion=str(item.get("criterion", ""))[:200],
            detail=str(item.get("detail", ""))[:MAX_REASON_CHARS],
        ))
    # Deterministic order, so two runs of the same samples read identically.
    return tuple(sorted(collected, key=lambda item: (item.criterion, item.detail)))


def parse_verdict(text: str, scale: ScoreScale) -> Verdict:
    """Parse one judge completion, or raise `JudgeContractError`."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise JudgeContractError("judge response is not valid JSON") from None
    if not isinstance(payload, dict):
        raise JudgeContractError("judge response is not a JSON object")

    verdict = payload.get("verdict")
    if verdict not in VERDICTS:
        raise JudgeContractError(
            f"judge verdict must be one of {list(VERDICTS)}"
        )

    score = _number(payload, "score", required=True, default=0.0)
    if not scale.contains(score):
        # Ignoring the declared scale invalidates the number entirely; clamping
        # would silently manufacture a score the rubric never sanctioned.
        raise JudgeContractError(
            f"judge score {score} is outside the configured scale "
            f"{scale.minimum}..{scale.maximum}"
        )

    confidence = _number(payload, "confidence", required=False, default=1.0)
    if not 0.0 <= confidence <= 1.0:
        raise JudgeContractError("judge confidence must be between 0 and 1")

    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise JudgeContractError("judge response is missing a reason")

    return Verdict(
        verdict=verdict,
        score=scale.normalize(score),
        confidence=confidence,
        reason=reason.strip()[:MAX_REASON_CHARS],
        violations=_violations(payload),
    )
