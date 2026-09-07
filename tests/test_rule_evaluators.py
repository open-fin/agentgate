from agentgate.control_plane import EvaluationService
from agentgate.domain import (
    Dimension, FailureStage, Kind, Outcome, RuleEvaluatorSpec, SpanKind, Trace, TraceSpan,
)
from agentgate.evaluator import EVALUATORS
from agentgate.evaluator.calc_score import calculate_result
from agentgate.evaluator.models import CheckDraft, Evaluation, FailureCandidate
from agentgate.storage.sqlite import SQLiteRepository

RULE_IDS = [item.id for item in EVALUATORS if item.kind == Kind.RULE]


def results_by_case(report):
    return {(item.case_id, item.evaluator_id): item for item in report.results}


def test_default_evaluators_keep_details_and_trace_ordered_primary_failure(tmp_path):
    service = EvaluationService(SQLiteRepository(tmp_path / "rules.db"))
    run = service.launch("loan-agent-v1-risky", evaluator_ids=RULE_IDS)
    report = service.run_detail(run.id)
    assert len(report.results) == 35  # 7 Rule evaluators over 5 cases
    by_id = {
        evaluator: item for (case, evaluator), item in results_by_case(report).items()
        if case == "high-risk-approval"
    }
    assert by_id["skill-routing"].outcome == Outcome.PASS
    assert by_id["tool-arguments"].outcome == Outcome.NOT_APPLICABLE
    assert by_id["final-output"].outcome == Outcome.NOT_APPLICABLE
    assert by_id["policy-compliance"].primary_failure_step == FailureStage.TOOL_SELECTION
    assert len(by_id["policy-compliance"].checks) == 2
    assert any(item.outcome == Outcome.FAIL for item in by_id["policy-compliance"].checks)
    assert all(item.turn_id == "high-risk-turn-1" for item in by_id["final-state"].checks)
    assert by_id["final-state"].checks[0].expected["kind"] == "equals"


def test_rules_cannot_catch_a_semantically_misleading_reply(tmp_path):
    """v3 takes the right action and lies about it: every Rule still passes."""
    service = EvaluationService(SQLiteRepository(tmp_path / "misleading.db"))
    run = service.launch("loan-agent-v3-misleading", evaluator_ids=RULE_IDS)
    report = service.run_detail(run.id)
    high_risk = [
        item for item in report.results if item.case_id == "high-risk-approval"
    ]
    rules = [item for item in high_risk if item.evaluator_kind == "rule"]
    assert rules and all(item.outcome != Outcome.FAIL for item in rules)
    assert report.gate.outcome == "pass"


def test_primary_failure_uses_trace_sequence_not_enum_order():
    trace = Trace(
        run_id="run",
        case_id="case",
        spans=(
            TraceSpan(id="routing", trace_id="trace", name="route",
                      kind=SpanKind.ROUTING, sequence=5),
            TraceSpan(id="state", trace_id="trace", name="state",
                      kind=SpanKind.STATE, sequence=1),
        ),
    )
    spec = RuleEvaluatorSpec(
        id="ordered", name="ordered", evaluator_type="final_state",
        dimension=Dimension.STATE, metric="ordered",
    )
    evaluation = Evaluation(checks=(
        CheckDraft(
            name="routing", outcome=Outcome.FAIL, score=0, reason="routing",
            failure=FailureCandidate(stage=FailureStage.ROUTING, span_id="routing"),
        ),
        CheckDraft(
            name="state", outcome=Outcome.FAIL, score=0, reason="state",
            failure=FailureCandidate(stage=FailureStage.FINAL_STATE, span_id="state"),
        ),
    ))
    result = calculate_result(spec, "run", "case", trace, evaluation)
    assert result.primary_failure_step == FailureStage.FINAL_STATE
