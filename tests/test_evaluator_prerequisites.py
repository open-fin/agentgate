import json

import pytest

from agentgate.domain import (
    Case, CaseTurn, ChildRef, Dimension, ExecutionPhase, HybridEvaluatorSpec,
    JudgeConfig, Kind, LlmJudgeEvaluatorSpec, Outcome, PrerequisitePolicy,
    PrerequisiteRef, PromptSnapshot, RubricSnapshot, RuleEvaluatorSpec, Trace,
)
from agentgate.evaluator.base import Evaluator
from agentgate.evaluator.models import (
    EvaluationContext, Evaluation, EvaluatorVersionMismatch,
    InvalidEvaluatorConfiguration, InvalidHybridEvaluator, MissingEvaluatorDependency,
)
from agentgate.evaluator.registry import register_evaluator
from agentgate.evaluator.runner import evaluate_case
from agentgate.evaluator.validation import validate_evaluation_plan
from agentgate.integrations.model_providers import EnvCredentialResolver, FakeJudgeModel
from tests.test_judge_evaluator import judge_spec, verdict_json

SCRIPTED: dict[str, Outcome] = {}


@register_evaluator
class ScriptedRuleEvaluator(Evaluator):
    """Produces whatever outcome the test asked for, for the spec's id."""

    kind = Kind.RULE
    evaluator_type = "test_scripted"

    def evaluate(self, spec, turn, trace, resolve, context):
        from agentgate.domain import FailureStage
        from agentgate.evaluator.models import CheckDraft, FailureCandidate

        outcome = SCRIPTED.get(spec.id, Outcome.PASS)
        if outcome == Outcome.NOT_APPLICABLE:
            return Evaluation(checks=())
        if outcome == Outcome.ERROR:
            raise RuntimeError("scripted failure")
        return Evaluation(checks=(CheckDraft(
            name=spec.id,
            outcome=outcome,
            score={Outcome.PASS: 1.0, Outcome.FAIL: 0.0, Outcome.REVIEW: 0.5}[outcome],
            reason=spec.id,
            failure=FailureCandidate(
                stage=FailureStage.FINAL_STATE, at_trace_completion=True,
            ) if outcome == Outcome.FAIL else None,
        ),))


def rule(spec_id, prerequisites=(), version="1"):
    return RuleEvaluatorSpec(
        id=spec_id, name=spec_id, version=version, dimension=Dimension.STATE,
        metric=spec_id, evaluator_type="test_scripted", prerequisites=prerequisites,
    )


def gated_judge(policy=PrerequisitePolicy.ON_PASS_OR_REVIEW, on="structural"):
    spec = judge_spec()
    return spec.model_copy(update={
        "prerequisites": (PrerequisiteRef(evaluator_id=on, version="1", policy=policy),),
    })


def case():
    return Case(id="c", name="c", turns=(CaseTurn(id="t", input={"m": "hi"}),))


def trace():
    return Trace(run_id="run", case_id="c", spans=(), final_output={"answer": "ok"})


def run(specs, model=None):
    return evaluate_case(
        case(), trace(), specs,
        EvaluationContext(judge_client=model or FakeJudgeModel(verdict_json())),
    )


def by_id(results):
    return {item.evaluator_id: item for item in results}


# --- prerequisite gating -----------------------------------------------------

@pytest.mark.parametrize("blocker", [Outcome.FAIL, Outcome.ERROR])
def test_a_blocking_prerequisite_withholds_the_judge_without_calling_a_model(blocker):
    SCRIPTED.clear()
    SCRIPTED["structural"] = blocker
    model = FakeJudgeModel(verdict_json())
    results = by_id(run((rule("structural"), gated_judge()), model))
    judged = results["answer-quality"]
    assert judged.outcome == Outcome.NOT_APPLICABLE
    assert judged.score is None
    assert "structural" in judged.reason
    assert model.call_count == 0
    # The blocking result stands on its own so the Gate still sees it.
    assert results["structural"].outcome == blocker


@pytest.mark.parametrize("blocker", [Outcome.PASS, Outcome.REVIEW, Outcome.NOT_APPLICABLE])
def test_a_permitting_prerequisite_lets_the_judge_run(blocker):
    SCRIPTED.clear()
    SCRIPTED["structural"] = blocker
    model = FakeJudgeModel(verdict_json())
    results = by_id(run((rule("structural"), gated_judge()), model))
    assert results["answer-quality"].outcome == Outcome.PASS
    assert model.call_count == 1


def test_on_pass_policy_also_blocks_a_review():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.REVIEW
    model = FakeJudgeModel(verdict_json())
    results = by_id(run(
        (rule("structural"), gated_judge(PrerequisitePolicy.ON_PASS)), model,
    ))
    assert results["answer-quality"].outcome == Outcome.NOT_APPLICABLE
    assert model.call_count == 0


def test_a_not_applicable_prerequisite_never_blocks_even_under_on_pass():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.NOT_APPLICABLE
    model = FakeJudgeModel(verdict_json())
    results = by_id(run(
        (rule("structural"), gated_judge(PrerequisitePolicy.ON_PASS)), model,
    ))
    assert results["answer-quality"].outcome == Outcome.PASS
    assert model.call_count == 1


def test_always_policy_declares_order_without_gating():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.FAIL
    model = FakeJudgeModel(verdict_json())
    results = by_id(run(
        (rule("structural"), gated_judge(PrerequisitePolicy.ALWAYS)), model,
    ))
    assert results["answer-quality"].outcome == Outcome.PASS
    assert model.call_count == 1


def test_blocking_severity_is_not_an_implicit_short_circuit():
    """A blocking failure vetoes the Gate; it does not silently skip evaluators."""
    from agentgate.domain import Severity

    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.FAIL
    blocking = rule("structural").model_copy(update={"severity": Severity.BLOCKING})
    model = FakeJudgeModel(verdict_json())
    results = by_id(run((blocking, judge_spec()), model))
    assert results["answer-quality"].outcome == Outcome.PASS
    assert model.call_count == 1


def test_a_prerequisite_is_evaluated_once_and_shared():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.PASS
    first = rule("a", (PrerequisiteRef(evaluator_id="structural", version="1"),))
    second = rule("b", (PrerequisiteRef(evaluator_id="structural", version="1"),))
    results = run((rule("structural"), first, second))
    assert len(results) == 3
    assert all(item.outcome == Outcome.PASS for item in results)


# --- plan validation ---------------------------------------------------------

def plan_of(*specs):
    from agentgate.demo.loan import LOAN_DATASET_VERSION
    return LOAN_DATASET_VERSION, specs


def test_unknown_prerequisite_is_rejected_before_the_run():
    dataset, specs = plan_of(rule("a", (PrerequisiteRef(evaluator_id="ghost", version="1"),)))
    with pytest.raises(MissingEvaluatorDependency):
        validate_evaluation_plan(dataset, specs)


def test_prerequisite_version_drift_is_rejected():
    dataset, specs = plan_of(
        rule("structural", version="2"),
        rule("a", (PrerequisiteRef(evaluator_id="structural", version="1"),)),
    )
    with pytest.raises(EvaluatorVersionMismatch):
        validate_evaluation_plan(dataset, specs)


def test_an_evaluator_cannot_gate_itself():
    dataset, specs = plan_of(rule("a", (PrerequisiteRef(evaluator_id="a", version="1"),)))
    with pytest.raises(InvalidEvaluatorConfiguration, match="cannot gate itself"):
        validate_evaluation_plan(dataset, specs)


def test_a_rule_cannot_depend_on_a_later_judge_phase():
    dataset, specs = plan_of(
        judge_spec(),
        rule("a", (PrerequisiteRef(evaluator_id="answer-quality", version="1"),)),
    )
    with pytest.raises(InvalidEvaluatorConfiguration, match="later"):
        validate_evaluation_plan(dataset, specs)


def test_empty_judge_prompt_or_rubric_is_rejected():
    dataset, _ = plan_of()
    with pytest.raises(InvalidEvaluatorConfiguration, match="empty judge prompt"):
        validate_evaluation_plan(dataset, (judge_spec(prompt_content="   "),))
    with pytest.raises(InvalidEvaluatorConfiguration, match="empty judge rubric"):
        validate_evaluation_plan(dataset, (judge_spec(rubric_content={}),))


def test_an_even_judge_panel_is_rejected():
    dataset, _ = plan_of()
    with pytest.raises(InvalidEvaluatorConfiguration, match="odd count"):
        validate_evaluation_plan(dataset, (judge_spec(samples=2),))
    validate_evaluation_plan(dataset, (judge_spec(samples=3),))


def test_an_unavailable_credential_stops_the_run_before_it_starts(monkeypatch):
    monkeypatch.delenv("JUDGE_KEY", raising=False)
    dataset, _ = plan_of()
    spec = judge_spec(credential_ref="env:JUDGE_KEY")
    with pytest.raises(InvalidEvaluatorConfiguration, match="not available"):
        validate_evaluation_plan(dataset, (spec,), EnvCredentialResolver())
    monkeypatch.setenv("JUDGE_KEY", "sk-value")
    validate_evaluation_plan(dataset, (spec,), EnvCredentialResolver())


def test_credentials_are_unchecked_when_no_checker_is_supplied(monkeypatch):
    monkeypatch.delenv("JUDGE_KEY", raising=False)
    dataset, _ = plan_of()
    validate_evaluation_plan(dataset, (judge_spec(credential_ref="env:JUDGE_KEY"),))


# --- prompt and rubric provenance --------------------------------------------

def test_a_snapshot_cannot_claim_a_digest_it_does_not_have():
    with pytest.raises(ValueError, match="PromptSnapshot content hash mismatch"):
        PromptSnapshot(id="p", version="1", content="real", sha256="deadbeef")
    with pytest.raises(ValueError, match="RubricSnapshot content hash mismatch"):
        RubricSnapshot(id="r", version="1", content={"a": 1}, sha256="deadbeef")


def test_a_snapshot_computes_its_own_digest():
    first = PromptSnapshot(id="p", version="1", content="grade this")
    second = PromptSnapshot(id="p", version="1", content="grade this")
    assert first.sha256 == second.sha256 and len(first.sha256) == 64
    assert PromptSnapshot(id="p", version="1", content="other").sha256 != first.sha256


# --- hybrid combination ------------------------------------------------------

def hybrid(children, threshold=1.0):
    return HybridEvaluatorSpec(
        id="combo", name="组合", dimension=Dimension.ANSWER, metric="combined",
        evaluator_type="weighted", pass_threshold=threshold,
        children=tuple(
            ChildRef(evaluator_id=item, version="1", weight=weight)
            for item, weight in children
        ),
    )


def hybrid_run(children, threshold=1.0, verdict="pass", score=1.0):
    model = FakeJudgeModel(verdict_json(verdict, score))
    specs = (rule("structural"), judge_spec(), hybrid(children, threshold))
    return by_id(run(specs, model))["combo"]


def test_hybrid_combines_children_into_one_weighted_verdict():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.PASS
    result = hybrid_run([("structural", 1.0), ("answer-quality", 1.0)])
    assert result.outcome == Outcome.PASS
    assert result.score == 1.0
    assert result.evaluator_kind == Kind.HYBRID


def test_hybrid_weights_change_the_combined_score():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.FAIL
    result = hybrid_run([("structural", 1.0), ("answer-quality", 3.0)], threshold=0.7)
    # (1*0.0 + 3*1.0) / 4
    assert result.score == 0.75
    assert result.outcome == Outcome.PASS


def test_hybrid_fails_below_its_threshold():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.FAIL
    result = hybrid_run([("structural", 1.0), ("answer-quality", 1.0)], threshold=0.9)
    assert result.outcome == Outcome.FAIL
    assert result.primary_failure_step is not None


def test_hybrid_will_not_average_away_an_errored_child():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.ERROR
    result = hybrid_run([("structural", 1.0), ("answer-quality", 1.0)], threshold=0.0)
    assert result.outcome == Outcome.REVIEW
    assert "出错" in result.checks[0].reason


def test_hybrid_escalates_when_a_child_asked_for_review():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.PASS
    result = hybrid_run(
        [("structural", 1.0), ("answer-quality", 1.0)],
        threshold=0.0, verdict="uncertain", score=0.5,
    )
    assert result.outcome == Outcome.REVIEW


def test_hybrid_is_not_applicable_when_no_child_produced_a_score():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.NOT_APPLICABLE
    model = FakeJudgeModel(verdict_json())
    specs = (rule("structural"), hybrid([("structural", 1.0)]))
    assert by_id(run(specs, model))["combo"].outcome == Outcome.NOT_APPLICABLE


def test_hybrid_draws_one_conclusion_for_a_multi_turn_case():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.PASS
    multi_turn = Case(id="c", name="c", turns=(
        CaseTurn(id="t1", input={"m": "one"}), CaseTurn(id="t2", input={"m": "two"}),
    ))
    results = by_id(evaluate_case(
        multi_turn, trace(),
        (rule("structural"), judge_spec(), hybrid(
            [("structural", 1.0), ("answer-quality", 1.0)]
        )),
        EvaluationContext(judge_client=FakeJudgeModel(verdict_json())),
    ))
    assert len(results["combo"].checks) == 1
    assert results["combo"].checks[0].turn_id is None


def test_hybrid_still_requires_both_a_rule_and_a_judge_child():
    dataset, _ = plan_of()
    specs = (rule("structural"), hybrid([("structural", 1.0)]))
    with pytest.raises(InvalidHybridEvaluator, match="Rule and LLM Judge"):
        validate_evaluation_plan(dataset, specs)


def test_hybrid_specs_default_to_the_hybrid_phase():
    assert hybrid([("a", 1.0)]).execution_phase == ExecutionPhase.HYBRID


def test_hybrid_runs_after_the_judge_it_combines():
    SCRIPTED.clear()
    SCRIPTED["structural"] = Outcome.PASS
    order = []
    model = FakeJudgeModel(
        responses=lambda _r: order.append("judge") or verdict_json()
    )
    specs = (
        hybrid([("structural", 1.0), ("answer-quality", 1.0)]),
        judge_spec(), rule("structural"),
    )
    results = evaluate_case(
        case(), trace(), specs, EvaluationContext(judge_client=model),
    )
    assert [item.evaluator_id for item in results] == [
        "structural", "answer-quality", "combo",
    ]
    assert order == ["judge"]


def test_judge_and_hybrid_configuration_is_json_round_trippable():
    spec = hybrid([("structural", 1.0), ("answer-quality", 2.0)], threshold=0.5)
    assert HybridEvaluatorSpec.model_validate(spec.model_dump(mode="json")) == spec
    gated = gated_judge()
    restored = LlmJudgeEvaluatorSpec.model_validate(gated.model_dump(mode="json"))
    assert restored == gated
    assert restored.prerequisites[0].policy is PrerequisitePolicy.ON_PASS_OR_REVIEW
    assert json.loads(json.dumps(gated.model_dump(mode="json")))


def test_judge_config_fields_are_carried_into_the_spec():
    spec = judge_spec(samples=3, credential_ref="env:K", timeout_seconds=5.0)
    assert isinstance(spec.judge, JudgeConfig)
    assert (spec.judge.samples, spec.judge.timeout_seconds) == (3, 5.0)
    assert spec.judge.credential_ref == "env:K"
