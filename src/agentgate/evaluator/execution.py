"""Deterministic, phase-ordered evaluator execution plans."""

from __future__ import annotations

from collections.abc import Iterable

from agentgate.domain import EvaluatorSpec, ExecutionPhase

from .models import DuplicateEvaluatorId

PHASE_ORDER: tuple[ExecutionPhase, ...] = (
    ExecutionPhase.STRUCTURAL_RULE,
    ExecutionPhase.RULE,
    ExecutionPhase.LLM_JUDGE,
    ExecutionPhase.HYBRID,
)

_PHASE_RANK = {phase: index for index, phase in enumerate(PHASE_ORDER)}


def phase_rank(phase: ExecutionPhase) -> int:
    """Position of a phase in the execution order."""
    return _PHASE_RANK[phase]


def build_execution_plan(
    evaluators: Iterable[EvaluatorSpec],
) -> tuple[EvaluatorSpec, ...]:
    """Order selected evaluators by execution phase.

    Ordering is stable: evaluators inside one phase keep the caller's order, so
    the same selection always produces the same plan. Phase controls order only;
    it is not a dependency, a short circuit, or a scoring weight.
    """
    selected = tuple(evaluators)
    if len({item.id for item in selected}) != len(selected):
        raise DuplicateEvaluatorId("evaluator IDs must be unique")
    return tuple(sorted(selected, key=lambda spec: _PHASE_RANK[spec.execution_phase]))
