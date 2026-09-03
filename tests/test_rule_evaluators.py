from agentgate.control_plane import EvaluationService
from agentgate.domain import (
    Dimension, FailureStage, Outcome, RuleEvaluatorSpec, SpanKind, Trace, TraceSpan,
)
from agentgate.evaluator.calc_score import calculate_result
from agentgate.evaluator.models import CheckDraft, Evaluation, FailureCandidate
from agentgate.storage.sqlite import SQLiteRepository


def results_by_case(report):
    return {(item.case_id, item.evaluator_id): item for item in report.results}


def test_default_evaluators_keep_details_and_trace_ordered_primary_failure(tmp_path):
    service = EvaluationService(SQLiteRepository(tmp_path / "rules.db"))
    run = service.launch("loan-agent-v1-risky")
    report = service.run_detail(run.id)
    assert len(report.results) == 16  # 8 evaluators over 2 cases
    by_id = {
        evaluator: item for (case, evaluator), item in results_by_case(report).items()
        if case == "high-risk-approval"
    }
    # Policy already failed, so the judge is withheld rather than paid for.
    assert by_id["answer-quality"].outcome == Outcome.NOT_APPLICABLE
    assert "policy-compliance" in by_id["answer-quality"].reason
    assert by_id["skill-routing"].outcome == Outcome.PASS
    assert by_id["tool-arguments"].outcome == Outcome.NOT_APPLICABLE
    assert by_id["final-output"].outcome == Outcome.NOT_APPLICABLE
    assert by_id["policy-compliance"].primary_failure_step == FailureStage.TOOL_SELECTION
    assert len(by_id["policy-compliance"].checks) == 2
    assert any(item.outcome == Outcome.FAIL for item in by_id["policy-compliance"].checks)
    assert all(item.turn_id == "high-risk-turn-1" for item in by_id["final-state"].checks)
    assert by_id["final-state"].checks[0].expected["kind"] == "equals"


def test_the_judge_still_runs_on_cases_no_policy_rule_gates(tmp_path):
    """The gate must not make the judge invisible on an otherwise clean run."""
    service = EvaluationService(SQLiteRepository(tmp_path / "gated.db"))
    report = service.run_detail(service.launch("loan-agent-v1-risky").id)
    rows = results_by_case(report)
    assert rows[("high-risk-approval", "answer-quality")].outcome == Outcome.NOT_APPLICABLE
    assert rows[("low-risk-approval", "answer-quality")].outcome == Outcome.PASS


def test_only_the_judge_catches_a_reply_that_misleads_the_applicant(tmp_path):
    """v3 takes the right action and lies about it: every rule passes."""
    service = EvaluationService(SQLiteRepository(tmp_path / "misleading.db"))
    report = service.run_detail(service.launch("loan-agent-v3-misleading").id)
    high_risk = [
        item for item in report.results if item.case_id == "high-risk-approval"
    ]
    rules = [item for item in high_risk if item.evaluator_kind == "rule"]
    assert rules and all(item.outcome != Outcome.FAIL for item in rules)

    judged = next(item for item in high_risk if item.evaluator_id == "answer-quality")
    assert judged.outcome == Outcome.FAIL
    assert judged.primary_failure_step == FailureStage.FINAL_OUTPUT
    assert "宣称已获批准" in judged.checks[0].reason
    # And the release gate closes on evidence no deterministic rule produced.
    assert report.gate.outcome == "fail"


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
