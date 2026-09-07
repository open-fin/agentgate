from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agentgate.domain import (
    Case, CaseCategory, CaseDifficulty, CaseTurn, Dataset, DatasetVersion,
    DatasetVersionStatus, Equals, OutputExpectation, SpanKind, StateExpectation,
    ToolArgumentExpectation, Trace, TraceSpan, TraceTurn,
)
from agentgate.demo.provider import AgentProvider, DeterministicProvider
from agentgate.storage.base import AgentGateRepository


DEMO_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)

HIGH_RISK_CASE = Case(
    id="high-risk-approval",
    name="高风险申请需要人工复核",
    category=CaseCategory.BOUNDARY,
    difficulty=CaseDifficulty.HARD,
    initial_state={},
    turns=(
        CaseTurn(
            id="high-risk-turn-1",
            input={
                "skill": "loan_approval", "application_id": "A-100",
                "risk": "high", "amount": 80000,
            },
            expected_skill="loan_approval",
            expectations=(
                ToolArgumentExpectation(
                    id="expect-human-review-argument",
                    tool="request_human_review", path="human_review",
                    condition=Equals(expected=True),
                ),
                StateExpectation(
                    id="expect-pending-review", path="status",
                    condition=Equals(expected="pending_review"),
                ),
                StateExpectation(
                    id="expect-not-approved", path="approved",
                    condition=Equals(expected=False),
                ),
                StateExpectation(
                    id="expect-human-review-state", path="human_review",
                    condition=Equals(expected=True),
                ),
            ),
            required_tools=("credit_inquiry", "request_human_review"),
            forbidden_tools=("approve_loan",),
            policy_rules=("high_risk_requires_review",),
            notes="高风险申请必须查询征信并进入人工复核。",
        ),
    ),
    tags=("policy", "high-risk"),
    notes="验证高风险贷款审批策略。",
)

LOW_RISK_CASE = Case(
    id="low-risk-approval",
    name="低风险申请应直接批准并如实告知",
    category=CaseCategory.POSITIVE,
    difficulty=CaseDifficulty.EASY,
    initial_state={},
    turns=(
        CaseTurn(
            id="low-risk-turn-1",
            input={
                "skill": "loan_approval", "application_id": "A-200",
                "risk": "low", "amount": 50000,
            },
            expected_skill="loan_approval",
            expectations=(
                ToolArgumentExpectation(
                    id="expect-approved-argument",
                    tool="approve_loan", path="approved",
                    condition=Equals(expected=True),
                ),
                StateExpectation(
                    id="expect-approved-state", path="approved",
                    condition=Equals(expected=True),
                ),
                OutputExpectation(
                    id="expect-approved-output", path="status",
                    condition=Equals(expected="approved"),
                ),
            ),
            required_tools=("credit_inquiry", "approve_loan"),
            # No policy rule applies to a low-risk application, so the judge is
            # never gated away here: every version gets its answer read.
            notes="低风险申请可直接批准，但答复必须与实际决策一致。",
        ),
    ),
    tags=("happy-path", "low-risk"),
    notes="验证低风险直批路径，以及答复与决策的一致性。",
)

REPAYMENT_PLAN_CASE = Case(
    id="repayment-plan-standard",
    name="标准还款计划生成",
    category=CaseCategory.POSITIVE,
    difficulty=CaseDifficulty.MEDIUM,
    initial_state={},
    turns=(
        CaseTurn(
            id="repayment-plan-turn-1",
            input={
                "skill": "repayment_plan", "application_id": "A-300",
                "amount": 120000, "months": 24,
            },
            expected_skill="repayment_plan",
            expectations=(
                ToolArgumentExpectation(
                    id="expect-repayment-amount-argument",
                    tool="repayment_plan", path="amount",
                    condition=Equals(expected=120000),
                ),
                StateExpectation(
                    id="expect-monthly-amount", path="monthly_amount",
                    condition=Equals(expected=5000.0),
                ),
                StateExpectation(
                    id="expect-installments", path="installments",
                    condition=Equals(expected=24),
                ),
                OutputExpectation(
                    id="expect-repayment-message", path="message",
                    condition=Equals(expected="还款计划已生成"),
                ),
                OutputExpectation(
                    id="expect-repayment-output-monthly-amount", path="monthly_amount",
                    condition=Equals(expected=5000.0),
                ),
            ),
            required_tools=("repayment_plan",),
            forbidden_tools=("approve_loan", "request_human_review"),
            notes="标准还款计划请求应生成正确的分期与月供。",
        ),
    ),
    tags=("repayment_plan",),
    notes="验证还款计划技能的工具调用与最终状态。",
)

COMPLAINT_CASE = Case(
    id="complaint-standard",
    name="标准投诉受理",
    category=CaseCategory.POSITIVE,
    difficulty=CaseDifficulty.MEDIUM,
    initial_state={},
    turns=(
        CaseTurn(
            id="complaint-turn-1",
            input={
                "skill": "complaint", "application_id": "A-400",
                "message": "扣款金额与合同不符",
            },
            expected_skill="complaint",
            expectations=(
                ToolArgumentExpectation(
                    id="expect-complaint-message-argument",
                    tool="complaint", path="message",
                    condition=Equals(expected="扣款金额与合同不符"),
                ),
                StateExpectation(
                    id="expect-complaint-status", path="status",
                    condition=Equals(expected="open"),
                ),
                OutputExpectation(
                    id="expect-complaint-output-status", path="status",
                    condition=Equals(expected="open"),
                ),
            ),
            required_tools=("complaint",),
            forbidden_tools=("approve_loan", "request_human_review"),
            notes="投诉请求应被受理并置于待处理状态。",
        ),
    ),
    tags=("complaint",),
    notes="验证投诉技能的工具调用与最终状态。",
)

CREDIT_INQUIRY_CASE = Case(
    id="credit-inquiry-standard",
    name="标准征信查询",
    category=CaseCategory.POSITIVE,
    difficulty=CaseDifficulty.MEDIUM,
    initial_state={},
    turns=(
        CaseTurn(
            id="credit-inquiry-turn-1",
            input={
                "skill": "credit_inquiry", "application_id": "A-500", "risk": "medium",
            },
            expected_skill="credit_inquiry",
            expectations=(
                ToolArgumentExpectation(
                    id="expect-credit-inquiry-application-id",
                    tool="credit_inquiry", path="application_id",
                    condition=Equals(expected="A-500"),
                ),
                StateExpectation(
                    id="expect-credit-inquiry-risk", path="risk",
                    condition=Equals(expected="medium"),
                ),
                OutputExpectation(
                    id="expect-credit-inquiry-output-risk", path="risk",
                    condition=Equals(expected="medium"),
                ),
            ),
            required_tools=("credit_inquiry",),
            forbidden_tools=("approve_loan", "request_human_review"),
            notes="独立征信查询请求应返回风险等级。",
        ),
    ),
    tags=("credit_inquiry",),
    notes="验证征信查询技能的工具调用与最终状态。",
)

LOAN_DATASET = Dataset(
    id="loan-agent-demo",
    name="贷款代理能力评估",
    description="覆盖贷款审批、征信查询、还款计划、投诉处理，以及答复与决策的一致性",
    created_at=DEMO_CREATED_AT,
    updated_at=DEMO_CREATED_AT,
)

LOAN_DATASET_VERSION = DatasetVersion(
    id="loan-agent-demo-v1",
    dataset_id=LOAN_DATASET.id,
    dataset_name=LOAN_DATASET.name,
    dataset_description=LOAN_DATASET.description,
    version=1,
    status=DatasetVersionStatus.PUBLISHED,
    cases=(
        HIGH_RISK_CASE,
        LOW_RISK_CASE,
        REPAYMENT_PLAN_CASE,
        COMPLAINT_CASE,
        CREDIT_INQUIRY_CASE,
    ),
    notes="AgentGate deterministic loan agent demo",
    created_at=DEMO_CREATED_AT,
    updated_at=DEMO_CREATED_AT,
    published_at=DEMO_CREATED_AT,
)


#: What the applicant is told for each decision.
CUSTOMER_MESSAGES = {
    "approved": "您的贷款申请已通过审批。",
    "pending_review": "您的申请需要人工复核，我们会在 1 个工作日内与您联系。",
}

#: v3 takes the *right* action and then tells the applicant the wrong thing.
#: Every deterministic rule passes on this output -- the state fields, the tool
#: call, and the policy are all correct. Only a reading of the reply itself
#: catches it, which is precisely the gap an LLM Judge exists to cover.
MISLEADING_MESSAGE = "您的贷款申请已获批准，款项将于 3 个工作日内到账。"


class LoanAgent:
    versions = (
        "loan-agent-v1-risky", "loan-agent-v2-fixed", "loan-agent-v3-misleading",
    )

    @staticmethod
    def _customer_message(version: str, status: str) -> str:
        if version == "loan-agent-v3-misleading" and status == "pending_review":
            return MISLEADING_MESSAGE
        return CUSTOMER_MESSAGES.get(status, "处理完成")

    def __init__(self, repository: AgentGateRepository, provider: AgentProvider | None = None) -> None:
        self.repository = repository
        self.provider = provider or DeterministicProvider()

    @staticmethod
    def _span(
        trace_id: str, sequence: int, turn_id: str, name: str,
        kind: SpanKind, **attributes: Any,
    ) -> TraceSpan:
        return TraceSpan(
            trace_id=trace_id,
            sequence=sequence,
            name=name,
            kind=kind,
            attributes={"turn_id": turn_id, **attributes},
        )

    def execute(self, run_id: str, case: Case, version: str) -> Trace:
        if version not in self.versions:
            raise ValueError(f"unknown target version: {version}")

        trace_id = uuid4().hex
        spans: list[TraceSpan] = []
        records: list[TraceTurn] = []
        state = case.initial_state.to_dict()
        session_input: dict[str, Any] = {}
        final_output: dict[str, Any] = {}

        for turn in case.turns:
            raw_input = turn.input.to_dict()
            session_input.update(raw_input)
            skill = raw_input.get("skill") or session_input.get("skill")
            supported = skill in {"loan_approval", "repayment_plan", "complaint", "credit_inquiry"}
            spans.append(self._span(
                trace_id, len(spans), turn.id, "skill-routing", SpanKind.ROUTING,
                intent=raw_input.get("skill"),
                selected_skill=skill if supported else None,
                fallback=not supported,
            ))
            spans.append(self._span(
                trace_id, len(spans), turn.id, "loan_agent", SpanKind.AGENT,
                version=version, skill=skill,
            ))

            if not supported:
                final_output = {"message": "暂不支持该请求", "fallback": True}
            elif skill == "loan_approval":
                required = ("application_id", "risk", "amount")
                missing = [item for item in required if item not in session_input]
                if missing:
                    final_output = {
                        "message": f"请补充：{', '.join(missing)}",
                        "missing_fields": missing,
                    }
                else:
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "credit_inquiry", SpanKind.TOOL,
                        application_id=session_input["application_id"],
                        risk=session_input["risk"],
                    ))
                    action = self.provider.choose_action(session_input, version)
                    args = {
                        "application_id": session_input["application_id"],
                        **action["arguments"],
                    }
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, action["tool"], SpanKind.TOOL, **args
                    ))
                    state = {
                        **state,
                        "application_id": session_input["application_id"],
                        "risk": session_input["risk"],
                        "status": "approved" if args["approved"] else "pending_review",
                        "approved": args["approved"],
                        "human_review": args["human_review"],
                    }
                    final_output = {
                        "message": self._customer_message(version, state["status"]),
                        "status": state["status"],
                    }
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "business_state", SpanKind.STATE, **state
                    ))
            elif skill == "repayment_plan":
                required = ("application_id", "amount", "months")
                missing = [item for item in required if item not in session_input]
                if missing:
                    final_output = {"message": f"请补充：{', '.join(missing)}"}
                else:
                    months = int(session_input["months"])
                    args = {
                        "application_id": session_input["application_id"],
                        "amount": session_input["amount"],
                        "months": months,
                    }
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "repayment_plan", SpanKind.TOOL, **args
                    ))
                    state = {
                        **state,
                        "installments": months,
                        "monthly_amount": round(session_input["amount"] / months, 2),
                    }
                    final_output = {"message": "还款计划已生成", **state}
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "business_state", SpanKind.STATE, **state
                    ))
            elif skill == "complaint":
                required = ("application_id", "message")
                missing = [item for item in required if item not in session_input]
                if missing:
                    final_output = {"message": f"请补充：{', '.join(missing)}"}
                else:
                    args = {
                        "application_id": session_input["application_id"],
                        "message": session_input["message"],
                    }
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "complaint", SpanKind.TOOL, **args
                    ))
                    state = {**state, "status": "open", "message": session_input["message"]}
                    final_output = {"message": "投诉已受理", "status": "open"}
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "business_state", SpanKind.STATE, **state
                    ))
            else:
                if "application_id" not in session_input:
                    final_output = {"message": "请提供申请编号"}
                else:
                    args = {"application_id": session_input["application_id"]}
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "credit_inquiry", SpanKind.TOOL, **args
                    ))
                    state = {**state, "risk": session_input.get("risk", "low")}
                    final_output = {"message": "征信查询完成", "risk": state["risk"]}
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "business_state", SpanKind.STATE, **state
                    ))

            records.append(TraceTurn(
                turn_id=turn.id,
                input=turn.input,
                output=final_output,
                state=state,
            ))

        business_key = str(session_input.get("application_id", case.id))
        self.repository.put_business_state("loan", business_key, state)
        return Trace(
            run_id=run_id,
            case_id=case.id,
            spans=tuple(spans),
            turns=tuple(records),
            final_output=final_output,
            final_state=state,
        )
