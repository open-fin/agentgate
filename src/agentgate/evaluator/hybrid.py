"""Combine finished Rule and LLM Judge Results into one weighted judgement.

A Hybrid does not evaluate anything itself: it reads child Results that the
runner has already produced and memoized, so a child is executed once no matter
how many combinations reference it.

The combination rules are conservative on purpose. A Hybrid speaks with one
voice about a dimension, so it must not be able to average away a child that
failed outright, that asked for a human, or that never ran.
"""

from __future__ import annotations

from agentgate.domain import (
    FailureStage, HybridEvaluatorSpec, Kind, MethodRef, Outcome,
)

from .base import Evaluator
from .models import CheckDraft, Evaluation, FailureCandidate, InvalidHybridEvaluator
from .registry import register_evaluator


@register_evaluator
class WeightedHybridEvaluator(Evaluator):
    """Weighted combination with an explicit pass threshold."""

    kind = Kind.HYBRID
    evaluator_type = "weighted"
    #: Child Results are case-level, so the combination is drawn once per case.
    per_turn = False

    def evaluate(self, spec, turn, trace, resolve, context) -> Evaluation:
        if not isinstance(spec, HybridEvaluatorSpec):
            raise InvalidHybridEvaluator(f"{spec.id} is not a Hybrid specification")
        children = [(child, resolve(child.evaluator_id)) for child in spec.children]
        scored = [
            (child, result) for child, result in children if result.score is not None
        ]
        outcomes = {result.outcome for _, result in children}

        if not scored:
            return Evaluation(checks=(CheckDraft(
                name=spec.name,
                outcome=Outcome.NOT_APPLICABLE,
                reason="所有子评估器均无适用评分",
            ),))

        weight = sum(child.weight for child, _ in scored)
        score = sum(child.weight * result.score for child, result in scored) / weight
        detail = {
            result.evaluator_id: {
                "outcome": str(result.outcome),
                "score": result.score,
                "weight": child.weight,
            }
            for child, result in children
        }

        if Outcome.ERROR in outcomes:
            # An errored child is an unknown, not a zero. Averaging it in would
            # convert a broken evaluator into a confident agent score.
            outcome, reason = Outcome.REVIEW, "子评估器执行出错，无法得出组合结论"
        elif Outcome.REVIEW in outcomes:
            outcome, reason = Outcome.REVIEW, "子评估器要求人工复核"
        elif score >= spec.pass_threshold:
            outcome, reason = Outcome.PASS, f"加权得分 {score:.2f} 达到阈值"
        else:
            outcome, reason = (
                Outcome.FAIL,
                f"加权得分 {score:.2f} 低于阈值 {spec.pass_threshold:.2f}",
            )

        return Evaluation(checks=(CheckDraft(
            name=spec.name,
            outcome=outcome,
            score=score,
            reason=reason,
            expected={"pass_threshold": spec.pass_threshold},
            actual={"weighted_score": score, "children": detail},
            methods=(MethodRef(operator="weighted_mean", operator_version="1"),),
            failure=FailureCandidate(
                stage=self._stage(children), at_trace_completion=True,
            ) if outcome == Outcome.FAIL else None,
        ),))

    @staticmethod
    def _stage(children) -> FailureStage:
        """Attribute the combination's failure to the first failing child."""
        return next(
            (
                result.primary_failure_step for _, result in children
                if result.primary_failure_step is not None
            ),
            FailureStage.FINAL_OUTPUT,
        )
