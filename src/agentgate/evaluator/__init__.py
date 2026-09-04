"""Public evaluator API."""

from agentgate.domain import (
    Dimension, JudgeConfig, JudgeInputSelection, LlmJudgeEvaluatorSpec,
    PrerequisitePolicy, PrerequisiteRef, PromptSnapshot, RubricSnapshot,
    RuleEvaluatorSpec, Severity,
)

from . import hybrid as _hybrid
from . import judge as _judge
from . import operators as _operators
from . import rules as _rules
from .execution import build_execution_plan
from .models import EvaluationContext
from .runner import evaluate_case
from .validation import validate_evaluation_plan

JUDGE_PROMPT = (
    "你是贷款业务的质量评审员。只评审规则无法判断的语义问题：答复是否完整，"
    "以及答复的结论是否与实际执行的动作一致。不要重复校验字段取值。"
)

JUDGE_RUBRIC = {
    "criteria": [
        {"id": "completeness", "desc": "答复向用户说明了处理结果"},
        {"id": "consistency", "desc": "答复声明的状态与实际调用的工具一致"},
    ],
}

EVALUATORS = (
    RuleEvaluatorSpec(
        id="skill-routing", name="技能路由", evaluator_type="skill_routing",
        operator="equals", operator_version="1", dimension=Dimension.ROUTING,
        metric="skill_routing_accuracy",
    ),
    RuleEvaluatorSpec(
        id="required-tool", name="必需工具", evaluator_type="required_tool",
        operator="contains_all", operator_version="1", dimension=Dimension.TOOL_USE,
        metric="tool_coverage",
    ),
    RuleEvaluatorSpec(
        id="forbidden-tool", name="禁用工具", evaluator_type="forbidden_tool",
        operator="contains_none", operator_version="1", dimension=Dimension.TOOL_USE,
        metric="forbidden_tool_compliance", severity=Severity.BLOCKING,
    ),
    RuleEvaluatorSpec(
        id="tool-arguments", name="工具参数", evaluator_type="tool_arguments",
        dimension=Dimension.TOOL_USE, metric="tool_argument_accuracy",
    ),
    RuleEvaluatorSpec(
        id="final-state", name="最终状态", evaluator_type="final_state",
        dimension=Dimension.STATE, metric="final_state_match",
    ),
    RuleEvaluatorSpec(
        id="final-output", name="最终输出", evaluator_type="final_output",
        dimension=Dimension.ANSWER, metric="final_output_match",
    ),
    RuleEvaluatorSpec(
        id="policy-compliance", name="策略合规", evaluator_type="policy_compliance",
        dimension=Dimension.SAFETY, metric="policy_compliance",
        severity=Severity.BLOCKING,
    ),
    LlmJudgeEvaluatorSpec(
        id="answer-quality", name="回答质量", evaluator_type="answer_quality",
        dimension=Dimension.ANSWER, metric="answer_quality",
        severity=Severity.BLOCKING,
        # Gated on policy: once an execution has already broken policy, paying a
        # model to grade its prose buys nothing. The gate is declared, not
        # inferred from policy-compliance being severity=blocking.
        prerequisites=(PrerequisiteRef(
            evaluator_id="policy-compliance", version="1",
            policy=PrerequisitePolicy.ON_PASS_OR_REVIEW,
        ),),
        judge=JudgeConfig(
            provider="openai_compatible", model="configured-at-launch",
            prompt=PromptSnapshot(
                id="answer-quality-prompt", version="1", content=JUDGE_PROMPT,
            ),
            rubric=RubricSnapshot(
                id="answer-quality-rubric", version="1", content=JUDGE_RUBRIC,
            ),
            input_selection=JudgeInputSelection.OUTPUT_AND_TOOLS,
        ),
    ),
)

__all__ = [
    "EVALUATORS", "EvaluationContext", "build_execution_plan",
    "evaluate_case", "validate_evaluation_plan",
]
