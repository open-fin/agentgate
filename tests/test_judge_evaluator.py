import json

import pytest

from agentgate.domain import (
    Case, CaseTurn, Dimension, ExecutionPhase, GateSpec, JudgeConfig,
    JudgeInputSelection, Kind, LlmJudgeEvaluatorSpec, MetricPlan, Outcome,
    PromptSnapshot, RubricSnapshot, RuleEvaluatorSpec, RunSnapshot, ScoreScale,
    SpanKind, TargetSnapshot, Trace, TraceSpan,
)
from agentgate.domain.base import content_sha256
from agentgate.evaluator.base import Evaluator
from agentgate.evaluator.judge import (
    JudgeContractError, JudgeModelTimeout, build_judge_request, parse_verdict,
)
from agentgate.evaluator.models import Evaluation, EvaluationContext
from agentgate.evaluator.registry import register_evaluator
from agentgate.evaluator.runner import evaluate_case
from agentgate.integrations.model_providers import FakeJudgeModel, always_fail
from agentgate.trace.redaction import DefaultRedactor

ID_CARD = "110101199003074567"
PHONE = "13800138000"
CARD = "6222021234567890123"
EMAIL = "borrower@example.com"

ORDER: list[str] = []


@register_evaluator
class OrderingRuleEvaluator(Evaluator):
    kind = Kind.RULE
    evaluator_type = "test_order_rule"

    def evaluate(self, spec, turn, trace, resolve, context):
        ORDER.append(spec.id)
        return Evaluation(checks=())


def verdict_json(verdict="pass", score=1.0, confidence=1.0, reason="looks right", **extra):
    return json.dumps({
        "verdict": verdict, "score": score, "confidence": confidence,
        "reason": reason, **extra,
    })


def judge_spec(spec_id="answer-quality", **judge_overrides):
    content = judge_overrides.pop("prompt_content", "You grade loan agents.")
    rubric = judge_overrides.pop("rubric_content", {"criteria": ["correct", "complete"]})
    judge_overrides.setdefault("model", "judge-1")
    return LlmJudgeEvaluatorSpec(
        id=spec_id, name="回答质量", dimension=Dimension.ANSWER,
        metric="answer_quality", evaluator_type="answer_quality",
        judge=JudgeConfig(
            provider="fake",
            prompt=PromptSnapshot(
                id="p", version="1", content=content, sha256=content_sha256(content),
            ),
            rubric=RubricSnapshot(
                id="r", version="1", content=rubric, sha256=content_sha256(rubric),
            ),
            **judge_overrides,
        ),
    )


def rule_spec(spec_id):
    return RuleEvaluatorSpec(
        id=spec_id, name=spec_id, dimension=Dimension.STATE, metric=spec_id,
        evaluator_type="test_order_rule",
    )


def case(**turn_overrides):
    return Case(id="c", name="c", turns=(CaseTurn(id="t", input={"m": "hi"}, **turn_overrides),))


def trace(final_output=None, spans=(), final_state=None):
    return Trace(
        run_id="run", case_id="c", spans=spans,
        final_output={"answer": "approved"} if final_output is None else final_output,
        final_state=final_state or {},
    )


def run(specs, model, the_case=None, the_trace=None):
    context = EvaluationContext(judge_client=model)
    return evaluate_case(the_case or case(), the_trace or trace(), specs, context)


# --- outcome mapping ---------------------------------------------------------

def test_pass_verdict_becomes_a_passing_result():
    [result] = run((judge_spec(),), FakeJudgeModel(verdict_json(score=1.0)))
    assert result.outcome == Outcome.PASS
    assert result.score == 1.0
    assert result.evaluator_kind == Kind.LLM_JUDGE


def test_fail_verdict_becomes_a_failure_observed_at_trace_completion():
    [result] = run(
        (judge_spec(),),
        FakeJudgeModel(verdict_json("fail", 0.0, reason="金额算错")),
    )
    assert result.outcome == Outcome.FAIL
    assert result.score == 0.0
    assert result.primary_failure_step == "final_output"
    assert result.checks[0].reason == "金额算错"


def test_uncertain_verdict_becomes_review_not_failure():
    [result] = run((judge_spec(),), FakeJudgeModel(verdict_json("uncertain", 0.5)))
    assert result.outcome == Outcome.REVIEW
    assert result.primary_failure_step is None


def test_low_confidence_downgrades_a_pass_to_review():
    [result] = run(
        (judge_spec(min_confidence=0.8),),
        FakeJudgeModel(verdict_json("pass", 1.0, confidence=0.4)),
    )
    assert result.outcome == Outcome.REVIEW
    assert "置信度" in result.checks[0].reason


def test_missing_output_is_not_applicable_and_calls_no_model():
    model = FakeJudgeModel(verdict_json())
    [result] = run((judge_spec(),), model, the_trace=trace(final_output={}))
    assert result.outcome == Outcome.NOT_APPLICABLE
    assert result.score is None and model.call_count == 0


# --- judge malfunction is ERROR, never FAIL ----------------------------------

def test_non_json_response_is_an_evaluator_error_not_an_agent_failure():
    [result] = run((judge_spec(),), FakeJudgeModel("the answer looks fine to me"))
    assert result.outcome == Outcome.ERROR
    assert result.error_evidence.category == "invalid_output"
    assert result.score is None and result.primary_failure_step is None


def test_timeout_is_a_retryable_evaluator_error():
    [result] = run((judge_spec(),), always_fail(JudgeModelTimeout("slow")))
    assert result.outcome == Outcome.ERROR
    assert result.error_evidence.category == "timeout"
    assert result.error_evidence.retryable is True


def test_score_outside_the_configured_scale_is_an_error():
    [result] = run(
        (judge_spec(score_scale=ScoreScale(minimum=0, maximum=5)),),
        FakeJudgeModel(verdict_json(score=9.0)),
    )
    assert result.outcome == Outcome.ERROR
    assert result.error_evidence.category == "invalid_output"


def test_missing_judge_model_is_an_error_not_a_silent_pass():
    results = evaluate_case(case(), trace(), (judge_spec(),), EvaluationContext())
    assert results[0].outcome == Outcome.ERROR
    assert results[0].error_evidence.exception_type == "JudgeNotConfigured"


@pytest.mark.parametrize("text", [
    '{"verdict": "maybe", "score": 1, "reason": "x"}',
    '{"verdict": "pass", "reason": "x"}',
    '{"verdict": "pass", "score": "high", "reason": "x"}',
    '{"verdict": "pass", "score": 1}',
    '{"verdict": "pass", "score": 1, "reason": "x", "confidence": 3}',
    '["pass"]',
])
def test_contract_violations_are_rejected(text):
    with pytest.raises(JudgeContractError):
        parse_verdict(text, ScoreScale())


def test_scores_are_normalised_from_the_configured_scale():
    scale = ScoreScale(minimum=0, maximum=10)
    assert parse_verdict(verdict_json(score=7.0), scale).score == 0.7


# --- sampling and voting -----------------------------------------------------

def test_majority_vote_decides_and_records_the_split():
    model = FakeJudgeModel([
        verdict_json("fail", 0.0, reason="错"),
        verdict_json("pass", 1.0),
        verdict_json("pass", 0.8),
    ])
    [result] = run((judge_spec(samples=3),), model)
    assert result.outcome == Outcome.PASS
    assert model.call_count == 3
    assert dict(result.judge_evidence.votes) == {"fail": 1, "pass": 2}
    assert result.judge_evidence.samples == 3
    assert len(result.judge_evidence.sample_responses) == 3
    # median of 0.0, 1.0, 0.8
    assert result.score == 0.8


def test_an_even_split_is_escalated_for_review():
    model = FakeJudgeModel([verdict_json("pass", 1.0), verdict_json("fail", 0.0)])
    [result] = run((judge_spec(samples=2),), model)
    assert result.outcome == Outcome.REVIEW
    assert "分歧" in result.checks[0].reason


def test_internal_correlation_ids_never_reach_the_judge():
    """turn_id is AgentGate bookkeeping, not agent behaviour.

    Leaking it would make otherwise equivalent requests differ for reasons that
    have nothing to do with the Agent's behaviour.
    """
    execution = trace(spans=(TraceSpan(
        id="s1", trace_id="t", name="approve_loan", kind=SpanKind.TOOL, sequence=0,
        attributes={"turn_id": "t-7", "approved": True},
    ),))
    model = FakeJudgeModel(verdict_json())
    run(
        (judge_spec(input_selection=JudgeInputSelection.FULL_TRAJECTORY),),
        model, the_trace=execution,
    )
    sent = model.last_request.user
    assert "approved" in sent          # behaviour is kept
    assert "turn_id" not in sent       # bookkeeping is not
    assert "t-7" not in sent


# --- redaction ---------------------------------------------------------------

def sensitive_trace():
    return Trace(
        run_id="run", case_id="c",
        spans=(TraceSpan(
            id="s1", trace_id="t", name="lookup_credit", kind=SpanKind.TOOL,
            sequence=0, attributes={"id_card": ID_CARD, "note": f"call {PHONE}"},
        ),),
        final_output={"message": f"已批准，卡号 {CARD}，邮箱 {EMAIL}"},
        final_state={"applicant_phone": PHONE},
    )


def test_no_sensitive_value_reaches_the_provider():
    model = FakeJudgeModel(verdict_json())
    run(
        (judge_spec(input_selection=JudgeInputSelection.FULL_TRAJECTORY),),
        model, the_trace=sensitive_trace(),
    )
    sent = model.last_request.user + (model.last_request.system or "")
    for secret in (ID_CARD, PHONE, CARD, EMAIL):
        assert secret not in sent
    assert "REDACTED" in sent


def test_redaction_keeps_the_trace_navigable():
    redacted = DefaultRedactor().redact_trace(sensitive_trace())
    assert redacted.spans[0].id == "s1"
    assert redacted.spans[0].name == "lookup_credit"
    assert redacted.spans[0].kind == SpanKind.TOOL
    assert redacted.spans[0].attributes["id_card"] == "[REDACTED:id_card]"
    assert PHONE not in redacted.spans[0].attributes["note"]
    assert CARD not in redacted.final_output["message"]


@pytest.mark.parametrize("field,expected", [
    ("applicant_phone", "[REDACTED:phone]"),
    ("customerIdCard", "[REDACTED:id_card]"),
    ("user_bank_card", "[REDACTED:bank_card]"),
    ("borrower_email", "[REDACTED:email]"),
])
def test_sensitive_terms_are_matched_inside_real_field_names(field, expected):
    """Payloads say `applicant_phone`, not `phone`; exact matching leaks."""
    assert DefaultRedactor().redact_value("whatever", field) == expected


@pytest.mark.parametrize("field", [
    "tokenizer", "phonetic_match", "amount", "application_id", "secretary_note",
])
def test_names_that_merely_contain_a_sensitive_substring_are_left_alone(field):
    assert DefaultRedactor().redact_value("keep me", field) == "keep me"


def test_a_card_number_stored_as_a_number_is_still_redacted():
    redactor = DefaultRedactor()
    assert redactor.redact_value(13800138000, "contact") == "[REDACTED:phone]"
    assert redactor.redact_value(6222021234567890123, "card") == "[REDACTED:bank_card]"


@pytest.mark.parametrize("amount", [80000, 30, 4.35, 999999999, 0])
def test_ordinary_numbers_survive_redaction(amount):
    """The judge still has to be able to reason about loan amounts."""
    assert DefaultRedactor().redact_value(amount, "amount") == amount


def test_an_eighteen_digit_id_is_not_mistaken_for_a_bank_card():
    assert DefaultRedactor().redact_text(f"证件 {ID_CARD}") == "证件 [REDACTED:id_card]"


def test_secrets_in_free_text_are_masked():
    masked = DefaultRedactor().redact_text("use api_key=sk-abcdefghijklmnop1234")
    assert "sk-abcdefghijklmnop1234" not in masked


# --- ordering, evidence, provenance ------------------------------------------

def test_every_deterministic_rule_runs_before_the_first_model_call():
    ORDER.clear()
    model = FakeJudgeModel(responses=lambda _r: ORDER.append("judge") or verdict_json())
    run((judge_spec(), rule_spec("rule-a"), rule_spec("rule-b")), model)
    assert ORDER == ["rule-a", "rule-b", "judge"]


def test_judge_specs_default_to_the_llm_judge_phase():
    assert judge_spec().execution_phase == ExecutionPhase.LLM_JUDGE


def test_evidence_records_what_the_decision_was_based_on():
    [result] = run((judge_spec(),), FakeJudgeModel(verdict_json(reason="ok")))
    evidence = result.judge_evidence
    assert evidence.requested_model == "judge-1"
    assert evidence.resolved_model == "fake-judge-1"
    assert evidence.prompt_sha256 and evidence.rubric_sha256
    assert json.loads(evidence.raw_response)["reason"] == "ok"
    assert evidence.request_id and evidence.input_tokens is not None
    assert evidence.latency_ms is not None and evidence.finish_reason == "stop"
    assert evidence.truncated is False and evidence.samples == 1


def test_judge_configuration_is_part_of_run_provenance():
    from datetime import UTC, datetime

    from agentgate.demo.loan import LOAN_DATASET_VERSION

    # Pinned so the comparison isolates JudgeConfig from the snapshot timestamp.
    created_at = datetime(2026, 9, 3, tzinfo=UTC)

    def build(spec):
        return RunSnapshot(
            dataset=LOAN_DATASET_VERSION, created_at=created_at,
            target=TargetSnapshot(name="t", version="1", provider="p"),
            evaluator_specs=(spec,), primary_evaluator_ids=(spec.id,),
            metric_plan=MetricPlan(), gate_spec=GateSpec(),
        )

    baseline = build(judge_spec())
    assert build(judge_spec()).snapshot_sha256 == baseline.snapshot_sha256
    for variant in (
        judge_spec(temperature=0.5), judge_spec(samples=3),
        judge_spec(prompt_content="new prompt"), judge_spec(credential_ref="env:K"),
        judge_spec(score_scale=ScoreScale(minimum=0, maximum=5)),
    ):
        assert build(variant).snapshot_sha256 != baseline.snapshot_sha256


def test_input_selection_controls_what_the_judge_can_see():
    execution = trace(
        spans=(TraceSpan(
            id="s1", trace_id="t", name="approve_loan", kind=SpanKind.TOOL,
            sequence=0, attributes={"approved": True},
        ),),
    )
    minimal = FakeJudgeModel(verdict_json())
    full = FakeJudgeModel(verdict_json())
    run((judge_spec(),), minimal, the_trace=execution)
    run(
        (judge_spec(input_selection=JudgeInputSelection.FULL_TRAJECTORY),),
        full, the_trace=execution,
    )
    assert "approve_loan" not in minimal.last_request.user
    assert "approve_loan" in full.last_request.user
