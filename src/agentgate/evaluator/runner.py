"""Evaluator execution with per-turn checks, memoization, and error Results."""

from __future__ import annotations

import logging
import re
from typing import Any

from agentgate.domain import (
    Case, EvaluationErrorEvidence, EvaluatorSpec, Outcome, PrerequisitePolicy,
    PrerequisiteRef, Result, Trace,
)

from .calc_score import calculate_result
from .execution import build_execution_plan
from .models import (
    CircularEvaluatorDependency, Evaluation, EvaluationContext,
    MissingEvaluatorDependency,
)
from .registry import resolve_evaluator

LOGGER = logging.getLogger(__name__)


def _safe_message(exc: Exception) -> str:
    message = str(exc)[:500]
    return re.sub(
        r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+",
        r"\1=[redacted]",
        message,
    )


def _error_result(spec: EvaluatorSpec, case: Case, trace: Trace, exc: Exception) -> Result:
    category = "timeout" if isinstance(exc, TimeoutError) else (
        "invalid_output" if isinstance(exc, (TypeError, ValueError)) else "crash"
    )
    LOGGER.exception("evaluator %s failed for case %s", spec.id, case.id)
    return Result(
        run_id=trace.run_id,
        case_id=case.id,
        evaluator_id=spec.id,
        evaluator_name=spec.name,
        evaluator_version=spec.version,
        evaluator_kind=spec.kind,
        dimension=spec.dimension,
        metric=spec.metric,
        severity=spec.severity,
        outcome=Outcome.ERROR,
        score=None,
        reason="评估器无法完成检查",
        error_evidence=EvaluationErrorEvidence(
            category=category,
            exception_type=type(exc).__name__,
            message=_safe_message(exc),
            retryable=category == "timeout",
        ),
    )


#: A prerequisite that returned NOT_APPLICABLE never blocks: having no opinion
#: is not a failure. ALWAYS declares ordering only and gates nothing.
PERMITTED_OUTCOMES: dict[PrerequisitePolicy, frozenset[Outcome]] = {
    PrerequisitePolicy.ON_PASS: frozenset({Outcome.PASS, Outcome.NOT_APPLICABLE}),
    PrerequisitePolicy.ON_PASS_OR_REVIEW: frozenset(
        {Outcome.PASS, Outcome.REVIEW, Outcome.NOT_APPLICABLE}
    ),
    PrerequisitePolicy.ALWAYS: frozenset(Outcome),
}


def _skipped_result(
    spec: EvaluatorSpec, case: Case, trace: Trace,
    prerequisite: PrerequisiteRef, blocker: Result,
) -> Result:
    """Record that a prerequisite withheld this evaluator.

    NOT_APPLICABLE, not FAIL: the agent was never judged on this dimension, so
    it must not be scored on it. The blocking Result stands on its own and the
    Gate still sees it, including when the blocker was an ERROR.
    """
    return Result(
        run_id=trace.run_id,
        case_id=case.id,
        evaluator_id=spec.id,
        evaluator_name=spec.name,
        evaluator_version=spec.version,
        evaluator_kind=spec.kind,
        dimension=spec.dimension,
        metric=spec.metric,
        severity=spec.severity,
        outcome=Outcome.NOT_APPLICABLE,
        score=None,
        reason=(
            f"前置评估器 {prerequisite.evaluator_id} 结果为 {blocker.outcome}，"
            f"依据策略 {prerequisite.policy} 跳过本次评估"
        ),
    )


def evaluate_case(
    case: Case, trace: Trace, evaluators: tuple[EvaluatorSpec, ...],
    context: EvaluationContext | None = None,
) -> list[Result]:
    plan = build_execution_plan(evaluators)
    by_id = {item.id: item for item in plan}
    context = context or EvaluationContext()

    cache: dict[str, Result] = {}
    resolving: set[str] = set()

    def resolve(spec_id: str) -> Result:
        if spec_id in cache:
            return cache[spec_id]
        if spec_id not in by_id:
            raise MissingEvaluatorDependency(spec_id)
        if spec_id in resolving:
            raise CircularEvaluatorDependency(spec_id)
        resolving.add(spec_id)
        spec = by_id[spec_id]
        try:
            blocked = next(
                (
                    (item, blocker) for item in spec.prerequisites
                    if (blocker := resolve(item.evaluator_id)).outcome
                    not in PERMITTED_OUTCOMES[item.policy]
                ),
                None,
            )
            if blocked is not None:
                # Gating happens here rather than inside each evaluator so no
                # implementation can forget it, and so a withheld LLM Judge is
                # guaranteed never to reach its provider.
                cache[spec_id] = _skipped_result(spec, case, trace, *blocked)
                return cache[spec_id]
            implementation = resolve_evaluator(spec)
            checks = []
            judge_evidence = None
            # A case-level evaluator sees the whole trace once and its checks
            # stay unattributed to any single turn.
            subjects = (
                [(turn, trace.for_turn(turn.id)) for turn in case.turns]
                if implementation.per_turn else [(case.turns[-1], trace)]
            )
            for turn, turn_trace in subjects:
                if not implementation.applies_to(spec, turn):
                    continue
                turn_evaluation: Any = implementation.evaluate(
                    spec, turn, turn_trace, resolve, context
                )
                if not isinstance(turn_evaluation, Evaluation):
                    raise TypeError("evaluator returned malformed Evaluation")
                checks.extend(
                    check if check.turn_id or not implementation.per_turn
                    else check.model_copy(update={"turn_id": turn.id})
                    for check in turn_evaluation.checks
                )
                judge_evidence = turn_evaluation.judge_evidence or judge_evidence
            evaluation = Evaluation(checks=tuple(checks), judge_evidence=judge_evidence)
            result = calculate_result(spec, trace.run_id, case.id, trace, evaluation)
        except Exception as exc:
            result = _error_result(spec, case, trace, exc)
        finally:
            resolving.discard(spec_id)
        cache[spec_id] = result
        return result

    return [resolve(item.id) for item in plan]
