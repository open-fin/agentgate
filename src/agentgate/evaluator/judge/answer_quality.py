"""Semantic answer-quality judging.

This is deliberately the only LLM Judge in the default set. Routing, tool
choice, tool arguments, final state, and output matching are already decided by
deterministic rules; handing those to a model would trade a reproducible answer
for an expensive, biased, and slower one. The judge covers what rules cannot
express: whether the answer is semantically correct, complete, and consistent
with the business rubric.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass

from agentgate.domain import (
    FailureStage, JudgeEvidence, Kind, LlmJudgeEvaluatorSpec, Outcome,
)

from ..base import Evaluator
from ..models import CheckDraft, Evaluation, EvaluationContext, FailureCandidate
from ..registry import register_evaluator
from .contract import FAIL, PASS, UNCERTAIN, Verdict, parse_verdict
from .model_protocol import JudgeResponse
from .prompt import build_judge_request


class JudgeNotConfigured(RuntimeError):
    """No judge model was supplied for a selected LLM Judge evaluator.

    A configuration gap, raised so it becomes an evaluator ERROR rather than a
    silent pass. Pre-run plan validation should catch this first.
    """


@dataclass(frozen=True)
class Decision:
    verdict: str
    score: float
    reason: str
    votes: dict[str, int]
    #: The trial that best explains the decision. It tracks the plurality
    #: winner, not the final verdict: when policy escalates to UNCERTAIN there
    #: is no trial that said "uncertain", but the leading trial is still the
    #: one worth recording as evidence.
    decisive_index: int


def decide(verdicts: list[Verdict], min_confidence: float) -> Decision:
    """Combine trials into one verdict, score, and reason.

    A strict majority carries the decision. An even split is not quietly
    tie-broken toward the safer-looking side: it is exactly the case a human
    should look at, so it becomes REVIEW.
    """
    counts = Counter(item.verdict for item in verdicts)
    label, votes = counts.most_common(1)[0]
    leader = next(i for i, item in enumerate(verdicts) if item.verdict == label)
    score = statistics.median(item.score for item in verdicts)
    confidence = statistics.mean(item.confidence for item in verdicts)

    if votes * 2 <= len(verdicts) and len(verdicts) > 1:
        reason, label = f"评审样本意见分歧：{dict(counts)}", UNCERTAIN
    elif confidence < min_confidence:
        reason = f"评审置信度 {confidence:.2f} 低于阈值 {min_confidence:.2f}"
        label = UNCERTAIN
    else:
        reason = verdicts[leader].reason
    return Decision(label, score, reason, dict(counts), leader)


@register_evaluator
class AnswerQualityJudge(Evaluator):
    kind = Kind.LLM_JUDGE
    evaluator_type = "answer_quality"

    def evaluate(self, spec, turn, trace, resolve, context) -> Evaluation:
        assert isinstance(spec, LlmJudgeEvaluatorSpec)
        judge = spec.judge

        if not trace.final_output:
            return Evaluation(checks=(CheckDraft(
                name=spec.name,
                outcome=Outcome.NOT_APPLICABLE,
                reason="本轮没有最终输出，无可评审内容",
            ),))
        if context.judge_client is None:
            raise JudgeNotConfigured(
                f"evaluator {spec.id} needs a judge model but none was supplied"
            )

        verdicts, responses = [], []
        for index in range(judge.samples):
            response = self._complete(spec, turn, trace, context, index)
            responses.append(response)
            verdicts.append(parse_verdict(response.text, judge.score_scale))

        decision = decide(verdicts, judge.min_confidence)
        return Evaluation(
            checks=(self._check(spec, decision, verdicts),),
            judge_evidence=self._evidence(
                spec, decision, responses
            ),
        )

    def _complete(
        self, spec, turn, trace, context: EvaluationContext, index: int
    ) -> JudgeResponse:
        # Redaction is not optional: every request is built through the
        # redactor before any material leaves the process.
        request = build_judge_request(spec, turn, trace, context.redactor, index)
        return context.judge_client.complete(request)

    def _check(
        self, spec, decision: "Decision", verdicts: list[Verdict]
    ) -> CheckDraft:
        outcome = {
            PASS: Outcome.PASS, FAIL: Outcome.FAIL, UNCERTAIN: Outcome.REVIEW,
        }[decision.verdict]
        violations = [
            f"{item.criterion}: {item.detail}"
            for verdict in verdicts for item in verdict.violations
        ]
        return CheckDraft(
            name=spec.name,
            outcome=outcome,
            score=decision.score,
            reason=decision.reason,
            expected={
                "rubric_sha256": spec.judge.rubric.sha256,
                "criteria": spec.judge.rubric.content,
            },
            actual={"verdict": decision.verdict, "violations": violations},
            # A judged failure is observed once the execution is complete; it
            # does not belong to any single span.
            failure=FailureCandidate(
                stage=FailureStage.FINAL_OUTPUT, at_trace_completion=True,
            ) if outcome == Outcome.FAIL else None,
        )

    def _evidence(
        self, spec, decision: "Decision", responses: list[JudgeResponse],
    ) -> JudgeEvidence:
        judge = spec.judge
        decisive = responses[decision.decisive_index]
        return JudgeEvidence(
            requested_model=judge.model,
            resolved_model=decisive.resolved_model,
            prompt_sha256=judge.prompt.sha256,
            rubric_sha256=judge.rubric.sha256,
            raw_response=decisive.text,
            request_id=decisive.request_id,
            input_tokens=_total(responses, "input_tokens"),
            output_tokens=_total(responses, "output_tokens"),
            latency_ms=_total(responses, "latency_ms"),
            samples=len(responses),
            votes=decision.votes,
            sample_responses=(
                tuple(item.text for item in responses) if len(responses) > 1 else ()
            ),
            finish_reason=decisive.finish_reason,
            truncated=any(item.truncated for item in responses),
            attempt_count=max(item.attempt_count for item in responses),
        )


def _total(responses: list[JudgeResponse], field: str):
    values = [getattr(item, field) for item in responses]
    known = [value for value in values if value is not None]
    return sum(known) if known else None


__all__ = ["AnswerQualityJudge", "Decision", "JudgeNotConfigured", "decide"]
