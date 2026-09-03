"""Persisted evaluator definitions and judge snapshots."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import DomainModel, FrozenJsonObject, content_sha256


class Kind(StrEnum):
    RULE = "rule"
    LLM_JUDGE = "llm_judge"
    HYBRID = "hybrid"


class Dimension(StrEnum):
    ROUTING = "routing"
    TOOL_USE = "tool_use"
    STATE = "state"
    ANSWER = "answer"
    SAFETY = "safety"
    EFFICIENCY = "efficiency"


class Severity(StrEnum):
    STANDARD = "standard"
    BLOCKING = "blocking"


class ExecutionPhase(StrEnum):
    """Ordering category for one evaluator inside a Run.

    Phase controls execution order only. It does not change score weight, Gate
    severity, or dependency semantics.
    """

    STRUCTURAL_RULE = "structural_rule"
    RULE = "rule"
    LLM_JUDGE = "llm_judge"
    HYBRID = "hybrid"


PHASES_BY_KIND: dict[Kind, frozenset[ExecutionPhase]] = {
    Kind.RULE: frozenset({ExecutionPhase.STRUCTURAL_RULE, ExecutionPhase.RULE}),
    Kind.LLM_JUDGE: frozenset({ExecutionPhase.LLM_JUDGE}),
    Kind.HYBRID: frozenset({ExecutionPhase.HYBRID}),
}


class MethodRef(DomainModel):
    operator: str
    operator_version: str
    condition_kind: str | None = None


class PromptSnapshot(DomainModel):
    id: str
    version: str
    content: str
    #: Computed when omitted, verified when supplied, so a snapshot can never
    #: claim a digest that does not describe its own content.
    sha256: str = ""

    @model_validator(mode="after")
    def set_or_verify_hash(self) -> "PromptSnapshot":
        expected = content_sha256(self.content)
        if self.sha256 and self.sha256 != expected:
            raise ValueError("PromptSnapshot content hash mismatch")
        if not self.sha256:
            object.__setattr__(self, "sha256", expected)
        return self


class RubricSnapshot(DomainModel):
    id: str
    version: str
    content: FrozenJsonObject
    sha256: str = ""

    @model_validator(mode="after")
    def set_or_verify_hash(self) -> "RubricSnapshot":
        expected = content_sha256(self.content)
        if self.sha256 and self.sha256 != expected:
            raise ValueError("RubricSnapshot content hash mismatch")
        if not self.sha256:
            object.__setattr__(self, "sha256", expected)
        return self


class JudgeInputSelection(StrEnum):
    """Which part of an execution the judge is allowed to read.

    Declared explicitly rather than inferred, because it decides cost, the
    verbosity bias the judge is exposed to, and how much material crosses the
    provider boundary.
    """

    FINAL_OUTPUT = "final_output"
    OUTPUT_AND_TOOLS = "output_and_tools"
    FULL_TRAJECTORY = "full_trajectory"


class ScoreScale(DomainModel):
    """The numeric range a judge is told to score on.

    Results always persist a normalized 0..1 score; this is only the scale the
    rubric speaks in.
    """

    minimum: float = 0.0
    maximum: float = 1.0

    @model_validator(mode="after")
    def validate_bounds(self) -> "ScoreScale":
        if self.maximum <= self.minimum:
            raise ValueError("score scale maximum must exceed minimum")
        return self

    def normalize(self, score: float) -> float:
        return (score - self.minimum) / (self.maximum - self.minimum)

    def contains(self, score: float) -> bool:
        return self.minimum <= score <= self.maximum


class JudgeConfig(DomainModel):
    provider: str
    model: str
    prompt: PromptSnapshot
    rubric: RubricSnapshot
    temperature: float = 0
    seed: int | None = None
    #: Reference to a secret, never a secret. Resolved by the model provider.
    credential_ref: str | None = None
    max_output_tokens: int | None = Field(default=1024, gt=0)
    timeout_seconds: float = Field(default=60.0, gt=0)
    #: Trials per judgement. Deterministic decoding is necessary but not
    #: sufficient for a stable verdict, so borderline cases can be voted on.
    #: Use an odd count: a panel of 2k needs as many concurring votes as one of
    #: 2k-1 while costing one more call, so even panels are rejected in
    #: pre-run validation.
    samples: int = Field(default=1, ge=1, le=9)
    #: Mean self-reported confidence below which a verdict becomes REVIEW.
    min_confidence: float = Field(default=0.0, ge=0, le=1)
    input_selection: JudgeInputSelection = JudgeInputSelection.FINAL_OUTPUT
    score_scale: ScoreScale = Field(default_factory=ScoreScale)
    #: Hard bound on rendered case material; protects cost and truncation.
    max_input_chars: int = Field(default=8000, gt=0)
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)


class JudgeEvidence(DomainModel):
    requested_model: str
    resolved_model: str | None = None
    prompt_sha256: str
    rubric_sha256: str
    #: The sample that decided the verdict.
    raw_response: str
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    samples: int = 1
    #: Verdict label to vote count, so a split decision stays auditable.
    votes: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    #: Every sample's raw text, recorded when more than one was taken.
    sample_responses: tuple[str, ...] = ()
    finish_reason: str | None = None
    truncated: bool = False
    attempt_count: int = 1


class PrerequisitePolicy(StrEnum):
    """Which prerequisite outcomes let a dependent evaluator run.

    A prerequisite that returned NOT_APPLICABLE never blocks under any policy:
    having no opinion is not a failure, and a structural check with nothing to
    check must not silently suppress semantic judging.
    """

    ON_PASS = "on_pass"
    ON_PASS_OR_REVIEW = "on_pass_or_review"
    #: Declares ordering and nothing else; the dependant always runs.
    ALWAYS = "always"


class PrerequisiteRef(DomainModel):
    """An explicit gate: run this evaluator only if another one permits it.

    Prerequisites exist so that skipping is always declared. Severity must never
    be repurposed as an implicit short circuit -- it decides whether a failure
    can veto the release Gate, which is a separate question from whether a
    later evaluator is worth running at all.
    """

    evaluator_id: str
    version: str
    policy: PrerequisitePolicy = PrerequisitePolicy.ON_PASS_OR_REVIEW


class ChildRef(DomainModel):
    evaluator_id: str
    version: str
    weight: float = Field(gt=0)


class EvaluatorBase(DomainModel):
    id: str
    name: str
    version: str = "1"
    dimension: Dimension
    metric: str
    severity: Severity = Severity.STANDARD
    execution_phase: ExecutionPhase = ExecutionPhase.RULE
    prerequisites: tuple[PrerequisiteRef, ...] = ()

    @model_validator(mode="after")
    def phase_matches_kind(self) -> "EvaluatorBase":
        kind = getattr(self, "kind", None)
        if kind is not None and self.execution_phase not in PHASES_BY_KIND[kind]:
            raise ValueError(
                f"{kind} evaluators cannot run in the {self.execution_phase} phase"
            )
        return self


class RuleEvaluatorSpec(EvaluatorBase):
    kind: Literal[Kind.RULE] = Kind.RULE
    evaluator_type: str
    operator: str | None = None
    operator_version: str | None = None
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)

    @model_validator(mode="after")
    def operator_fields_match(self) -> "RuleEvaluatorSpec":
        if (self.operator is None) != (self.operator_version is None):
            raise ValueError("operator and operator_version must both be present or absent")
        return self


class LlmJudgeEvaluatorSpec(EvaluatorBase):
    kind: Literal[Kind.LLM_JUDGE] = Kind.LLM_JUDGE
    execution_phase: ExecutionPhase = ExecutionPhase.LLM_JUDGE
    evaluator_type: str
    judge: JudgeConfig
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)


class HybridEvaluatorSpec(EvaluatorBase):
    kind: Literal[Kind.HYBRID] = Kind.HYBRID
    execution_phase: ExecutionPhase = ExecutionPhase.HYBRID
    evaluator_type: str
    children: tuple[ChildRef, ...]
    #: Weighted child score at or above which the combination passes. Defaults
    #: to strict agreement: relaxing it is a product decision that has to be
    #: made deliberately, not inherited from a convenient default.
    pass_threshold: float = Field(default=1.0, ge=0, le=1)
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)


EvaluatorSpec = Annotated[
    RuleEvaluatorSpec | LlmJudgeEvaluatorSpec | HybridEvaluatorSpec,
    Field(discriminator="kind"),
]
