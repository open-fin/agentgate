import pytest
from pydantic import ValidationError

from agentgate.domain import (
    Case, CaseTurn, Dimension, ExecutionPhase, HybridEvaluatorSpec, JudgeConfig, Kind,
    LlmJudgeEvaluatorSpec, PromptSnapshot, RubricSnapshot, RuleEvaluatorSpec, Trace,
)
from agentgate.domain.base import content_sha256
from agentgate.evaluator.base import Evaluator
from agentgate.evaluator.execution import PHASE_ORDER, build_execution_plan
from agentgate.evaluator.models import (
    DuplicateEvaluatorId, Evaluation, EvaluationContext,
)
from agentgate.evaluator.registry import register_evaluator
from agentgate.evaluator.runner import evaluate_case

SEEN: list[tuple[str, EvaluationContext]] = []


@register_evaluator
class RecordingEvaluator(Evaluator):
    kind = Kind.RULE
    evaluator_type = "test_recording"

    def evaluate(self, spec, turn, trace, resolve, context):
        SEEN.append((spec.id, context))
        return Evaluation(checks=())


def rule_spec(spec_id, phase=ExecutionPhase.RULE, evaluator_type="test_recording"):
    return RuleEvaluatorSpec(
        id=spec_id, name=spec_id, dimension=Dimension.STATE, metric=spec_id,
        evaluator_type=evaluator_type, execution_phase=phase,
    )


def judge_spec(spec_id):
    prompt = PromptSnapshot(
        id="p", version="1", content="score it", sha256=content_sha256("score it"),
    )
    rubric = RubricSnapshot(id="r", version="1", content={}, sha256=content_sha256({}))
    return LlmJudgeEvaluatorSpec(
        id=spec_id, name=spec_id, dimension=Dimension.ANSWER, metric=spec_id,
        evaluator_type="answer_quality",
        judge=JudgeConfig(provider="fake", model="fake-1", prompt=prompt, rubric=rubric),
    )


def hybrid_spec(spec_id, children):
    return HybridEvaluatorSpec(
        id=spec_id, name=spec_id, dimension=Dimension.ANSWER, metric=spec_id,
        evaluator_type="weighted", children=children,
    )


def simple_case():
    return Case(id="case", name="case", turns=(CaseTurn(id="turn", input={"m": "hi"}),))


def test_kinds_carry_their_own_default_phase():
    assert rule_spec("r").execution_phase == ExecutionPhase.RULE
    assert judge_spec("j").execution_phase == ExecutionPhase.LLM_JUDGE
    assert hybrid_spec("h", ()).execution_phase == ExecutionPhase.HYBRID


def test_phase_must_match_evaluator_kind():
    with pytest.raises(ValidationError, match="cannot run in the"):
        RuleEvaluatorSpec(
            id="r", name="r", dimension=Dimension.STATE, metric="r",
            evaluator_type="test_recording", execution_phase=ExecutionPhase.LLM_JUDGE,
        )


def test_plan_orders_by_phase_and_is_stable_within_a_phase():
    plan = build_execution_plan((
        hybrid_spec("hybrid", ()),
        judge_spec("judge"),
        rule_spec("rule-b"),
        rule_spec("rule-a"),
        rule_spec("structural", ExecutionPhase.STRUCTURAL_RULE),
    ))
    assert [item.id for item in plan] == [
        "structural", "rule-b", "rule-a", "judge", "hybrid",
    ]
    ranks = [PHASE_ORDER.index(item.execution_phase) for item in plan]
    assert ranks == sorted(ranks)


def test_plan_rejects_duplicate_evaluator_ids():
    with pytest.raises(DuplicateEvaluatorId):
        build_execution_plan((rule_spec("same"), rule_spec("same")))


def test_structural_rules_execute_before_other_rules():
    SEEN.clear()
    evaluate_case(
        simple_case(), Trace(run_id="run", case_id="case", spans=()),
        (rule_spec("rule"), rule_spec("structural", ExecutionPhase.STRUCTURAL_RULE)),
    )
    assert [spec_id for spec_id, _ in SEEN] == ["structural", "rule"]


def test_every_deterministic_phase_precedes_the_llm_judge_phase():
    judge_rank = PHASE_ORDER.index(ExecutionPhase.LLM_JUDGE)
    assert PHASE_ORDER.index(ExecutionPhase.STRUCTURAL_RULE) < judge_rank
    assert PHASE_ORDER.index(ExecutionPhase.RULE) < judge_rank
    assert PHASE_ORDER.index(ExecutionPhase.HYBRID) > judge_rank


def test_results_follow_plan_order_not_caller_order():
    results = evaluate_case(
        simple_case(), Trace(run_id="run", case_id="case", spans=()),
        (rule_spec("rule"), rule_spec("structural", ExecutionPhase.STRUCTURAL_RULE)),
    )
    assert [item.evaluator_id for item in results] == ["structural", "rule"]


def test_context_is_threaded_to_every_evaluator():
    SEEN.clear()
    context = EvaluationContext()
    evaluate_case(
        simple_case(), Trace(run_id="run", case_id="case", spans=()),
        (rule_spec("one"), rule_spec("two")), context,
    )
    assert [seen is context for _, seen in SEEN] == [True, True]


def test_runner_supplies_a_default_context_when_none_is_given():
    SEEN.clear()
    evaluate_case(
        simple_case(), Trace(run_id="run", case_id="case", spans=()),
        (rule_spec("one"),),
    )
    assert isinstance(SEEN[0][1], EvaluationContext)
