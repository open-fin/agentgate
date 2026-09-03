"""Evaluator execution interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from agentgate.domain import CaseTurn, EvaluatorSpec, Kind, Trace

from .models import Evaluation, EvaluationContext, ResultResolver


class Evaluator(ABC):
    kind: ClassVar[Kind]
    evaluator_type: ClassVar[str]

    #: Whether this evaluator judges each conversation turn separately. Set it
    #: False for evaluators whose subject is the case as a whole -- a Hybrid
    #: combining case-level child Results would otherwise emit one identical
    #: check per turn.
    per_turn: ClassVar[bool] = True

    def applies_to(self, spec: EvaluatorSpec, turn: CaseTurn) -> bool:
        return True

    @abstractmethod
    def evaluate(
        self, spec: EvaluatorSpec, turn: CaseTurn, trace: Trace,
        resolve: ResultResolver, context: EvaluationContext,
    ) -> Evaluation:
        raise NotImplementedError
