"""Render a judge completion request from a case, a trace, and a rubric.

The redactor is a required argument rather than an optional one. Building a
judge prompt is exactly the moment case material crosses the process boundary,
so the only way to send unredacted content is to construct a `JudgeRequest` by
hand -- which nothing in the judge path does.

Rendering is deterministic: canonical JSON with sorted keys, a fixed section
order, and a fixed truncation rule. Two evaluations of the same material
therefore produce byte-identical prompts for audit and testability.
"""

from __future__ import annotations

from typing import Any

from agentgate.domain import (
    CaseTurn, JudgeInputSelection, LlmJudgeEvaluatorSpec, SpanKind, Trace,
)
from agentgate.domain.base import canonical_json
from agentgate.domain.trace import INTERNAL_SPAN_ATTRIBUTES
from agentgate.trace.redaction import Redactor

from .contract import response_instructions
from .model_protocol import JudgeRequest

TRUNCATION_NOTE = "...[truncated]"


def _attributes(span) -> dict[str, Any]:
    """Span attributes minus AgentGate's own correlation bookkeeping.

    A judge is asked about behaviour, and internal ids are not behaviour. They
    would also make equivalent behaviour appear different for no semantic
    reason.
    """
    return {
        key: value for key, value in span.attributes.items()
        if key not in INTERNAL_SPAN_ATTRIBUTES
    }


def _tool_calls(trace: Trace) -> list[dict[str, Any]]:
    return [
        {"name": span.name, "arguments": _attributes(span), "status": span.status}
        for span in trace.spans
        if span.kind == SpanKind.TOOL
    ]


def _trajectory(trace: Trace) -> list[dict[str, Any]]:
    return [
        {
            "step": span.sequence,
            "kind": str(span.kind),
            "name": span.name,
            "attributes": _attributes(span),
            "status": span.status,
        }
        for span in sorted(trace.spans, key=lambda span: span.sequence)
    ]


def select_material(
    selection: JudgeInputSelection, turn: CaseTurn, trace: Trace
) -> dict[str, Any]:
    """Collect exactly the execution material the selection permits."""
    material: dict[str, Any] = {
        "task_input": turn.input,
        "final_output": trace.final_output,
    }
    if selection is JudgeInputSelection.OUTPUT_AND_TOOLS:
        material["tool_calls"] = _tool_calls(trace)
    elif selection is JudgeInputSelection.FULL_TRAJECTORY:
        material["tool_calls"] = _tool_calls(trace)
        material["trajectory"] = _trajectory(trace)
        material["final_state"] = trace.final_state
    return material


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - len(TRUNCATION_NOTE), 0)] + TRUNCATION_NOTE


def build_judge_request(
    spec: LlmJudgeEvaluatorSpec,
    turn: CaseTurn,
    trace: Trace,
    redactor: Redactor,
    sample_index: int = 0,
) -> JudgeRequest:
    """Render one judge request with all case material already redacted.

    `sample_index` shifts the seed so repeated trials are genuinely independent
    rather than the same greedy decode replayed.
    """
    judge = spec.judge
    material = select_material(judge.input_selection, turn, trace)
    redacted = redactor.redact_value(material)
    rendered = truncate(canonical_json(redacted), judge.max_input_chars)

    system = "\n\n".join([
        judge.prompt.content,
        "Rubric:\n" + canonical_json(judge.rubric.content),
        response_instructions(judge.score_scale),
    ])
    user = (
        f"Evaluate this agent execution against the rubric.\n"
        f"Material selection: {judge.input_selection}\n\n{rendered}"
    )
    seed = None if judge.seed is None else judge.seed + sample_index
    return JudgeRequest(
        model=judge.model,
        user=user,
        system=system,
        temperature=judge.temperature,
        seed=seed,
        max_output_tokens=judge.max_output_tokens,
        response_format="json_object",
        timeout_seconds=judge.timeout_seconds,
    )
