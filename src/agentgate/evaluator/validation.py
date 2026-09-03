"""Pre-run validation for a DatasetVersion and selected evaluator definitions.

Everything rejected here is a *configuration* fault, caught before a Run is
persisted. None of it may reach execution and become an evaluator ERROR, and
none of it may ever be recorded as the agent failing.
"""

from __future__ import annotations

from agentgate.domain import (
    DatasetVersion, HybridEvaluatorSpec, Kind, LlmJudgeEvaluatorSpec,
    MatchesJsonSchema, RuleEvaluatorSpec,
)

from .execution import build_execution_plan, phase_rank
from .judge.model_protocol import CredentialChecker
from .models import (
    EvaluatorVersionMismatch, InvalidEvaluatorConfiguration, InvalidHybridEvaluator,
    MissingEvaluatorDependency, UnsupportedOperator,
)
from .observations import condition_operator
from .registry import resolve_evaluator, resolve_operator


def _validate_judge(spec: LlmJudgeEvaluatorSpec, credentials: CredentialChecker | None):
    judge = spec.judge
    if not judge.prompt.content.strip():
        raise InvalidEvaluatorConfiguration(f"{spec.id} has an empty judge prompt")
    if not judge.rubric.content:
        raise InvalidEvaluatorConfiguration(f"{spec.id} has an empty judge rubric")
    if judge.samples % 2 == 0 and judge.samples > 1:
        # A panel of 2k needs the same number of concurring votes as one of
        # 2k-1, for one more model call: 2 and 3 both need 2, 4 and 5 both need
        # 3. An even panel is strictly more expensive and no more decisive.
        raise InvalidEvaluatorConfiguration(
            f"{spec.id} takes {judge.samples} judge samples; use an odd count "
            "so a majority can form"
        )
    if judge.credential_ref is None:
        return
    if credentials is not None and not credentials.is_available(judge.credential_ref):
        raise InvalidEvaluatorConfiguration(
            f"{spec.id} references credential {judge.credential_ref}, "
            "which is not available in this environment"
        )


def _validate_prerequisites(spec, by_id: dict) -> None:
    for prerequisite in spec.prerequisites:
        required = by_id.get(prerequisite.evaluator_id)
        if required is None:
            raise MissingEvaluatorDependency(prerequisite.evaluator_id)
        if required.version != prerequisite.version:
            raise EvaluatorVersionMismatch(prerequisite.evaluator_id)
        if required.id == spec.id:
            raise InvalidEvaluatorConfiguration(f"{spec.id} cannot gate itself")
        if phase_rank(required.execution_phase) > phase_rank(spec.execution_phase):
            # Otherwise a later phase would have to be pulled forward to decide
            # an earlier one, defeating the ordering guarantee entirely.
            raise InvalidEvaluatorConfiguration(
                f"{spec.id} cannot depend on {required.id}, which runs in the "
                f"later {required.execution_phase} phase"
            )


def validate_evaluation_plan(
    dataset: DatasetVersion, evaluators: tuple,
    credentials: CredentialChecker | None = None,
) -> None:
    """Validate a Run's evaluation plan.

    Credential availability is only checked when a `credentials` checker is
    supplied; without one an unresolvable reference is not detected until the
    provider is constructed.
    """
    plan = build_execution_plan(evaluators)
    by_id = {item.id: item for item in plan}

    metric_dimensions: dict[str, object] = {}
    for spec in plan:
        _validate_prerequisites(spec, by_id)
        if isinstance(spec, LlmJudgeEvaluatorSpec):
            _validate_judge(spec, credentials)
        previous = metric_dimensions.setdefault(spec.metric, spec.dimension)
        if previous != spec.dimension:
            raise ValueError(
                f"metric {spec.metric} cannot belong to both {previous} and {spec.dimension}"
            )
        if isinstance(spec, RuleEvaluatorSpec) and spec.operator:
            resolve_operator(spec.operator, spec.operator_version)
        if isinstance(spec, HybridEvaluatorSpec):
            children = []
            for child in spec.children:
                child_spec = by_id.get(child.evaluator_id)
                if child_spec is None:
                    raise MissingEvaluatorDependency(child.evaluator_id)
                if child.version != child_spec.version:
                    raise EvaluatorVersionMismatch(child.evaluator_id)
                children.append(child_spec)
            if any(item.kind == Kind.HYBRID for item in children):
                raise InvalidHybridEvaluator("nested Hybrid is not supported")
            kinds = {item.kind for item in children}
            if not {Kind.RULE, Kind.LLM_JUDGE}.issubset(kinds):
                raise InvalidHybridEvaluator("Hybrid requires Rule and LLM Judge children")
        resolve_evaluator(spec)

    for case in dataset.cases:
        for turn in case.turns:
            for expectation in turn.expectations:
                if isinstance(expectation.condition, MatchesJsonSchema):
                    raise UnsupportedOperator("JSON Schema evaluation is deferred")
                resolve_operator(condition_operator(expectation.condition), "1")
