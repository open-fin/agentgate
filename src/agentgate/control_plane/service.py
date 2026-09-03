"""Local control-plane service shared by CLI, HTTP, and the Web UI."""

from __future__ import annotations

import os

from agentgate.case import DatasetService
from agentgate.demo.judge import DemoJudgeModel
from agentgate.demo.loan import LOAN_DATASET, LOAN_DATASET_VERSION, LoanAgent
from agentgate.domain import LlmJudgeEvaluatorSpec
from agentgate.evaluator import EVALUATORS, EvaluationContext
from agentgate.integrations.model_providers import (
    EnvCredentialResolver, OpenAICompatibleJudgeModel,
)
from agentgate.run.core import RunEngine
from agentgate.storage.base import AgentGateRepository

#: Selectable judge keys. Only the *reference* is ever stored or returned; the
#: secret itself never enters a Run, an API response, or a log line.
JUDGE_CREDENTIALS: tuple[dict[str, str], ...] = (
    {
        "id": "public", "label": "平台公共 Key",
        "credential_ref": "env:AGENTGATE_JUDGE_API_KEY",
    },
    {
        "id": "private", "label": "用户私有 Key",
        "credential_ref": "env:AGENTGATE_JUDGE_API_KEY_PRIVATE",
    },
)

ENDPOINT_ENV = "AGENTGATE_JUDGE_ENDPOINT"
MODEL_ENV = "AGENTGATE_JUDGE_MODEL"

#: The three demo targets deliberately fail in different layers: v1 breaks a
#: rule, v3 breaks nothing a rule can see.
VERSION_LABELS = {
    "loan-agent-v1-risky": "风险版本 · 违反高风险政策",
    "loan-agent-v2-fixed": "修复版本 · 规则与答复均正确",
    "loan-agent-v3-misleading": "误导版本 · 规则全过，答复误导客户",
}


class EvaluationService:
    """Coordinate evaluation launches and read models for the local POC."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository
        self.engine = RunEngine(repository)
        self.credentials = EnvCredentialResolver()
        self.dataset_service = DatasetService(repository)
        self.dataset_service.seed(LOAN_DATASET, LOAN_DATASET_VERSION)

    def judge_credentials(self) -> list[dict]:
        """List selectable judge keys and whether each resolves here."""
        return [
            {**item, "available": self.credentials.is_available(item["credential_ref"])}
            for item in JUDGE_CREDENTIALS
        ]

    def _judge_model(self, credential_id: str | None):
        """Pick the judge client, and the identity the Run will record for it.

        Without a selected key the demo stand-in runs, which is what keeps a
        fresh checkout able to evaluate the judge path with no configuration.
        """
        if credential_id is None:
            return DemoJudgeModel(), None
        entry = next(
            (item for item in JUDGE_CREDENTIALS if item["id"] == credential_id), None
        )
        if entry is None:
            raise ValueError(f"unknown judge credential: {credential_id}")
        endpoint = os.getenv(ENDPOINT_ENV)
        if not endpoint:
            raise ValueError(
                f"{ENDPOINT_ENV} must be set to use a judge credential"
            )
        client = OpenAICompatibleJudgeModel(
            endpoint=endpoint,
            credential_ref=entry["credential_ref"],
            resolver=self.credentials,
        )
        return client, {
            "provider": client.provider,
            "model": os.getenv(MODEL_ENV, "gpt-4o-mini"),
            "credential_ref": entry["credential_ref"],
        }

    @staticmethod
    def _with_judge_identity(evaluators: tuple, identity: dict | None) -> tuple:
        """Record the provider actually used, not the one the default declared.

        The RunSnapshot is the audit record of how a verdict was reached, so it
        must not keep claiming the demo judge when a real one was called.
        """
        if identity is None:
            return evaluators
        return tuple(
            spec.model_copy(update={"judge": spec.judge.model_copy(update=identity)})
            if isinstance(spec, LlmJudgeEvaluatorSpec) else spec
            for spec in evaluators
        )

    def launch(
        self, version: str, dataset_id: str | None = None,
        dataset_version: int | None = None, evaluator_ids: list[str] | None = None,
        judge_credential: str | None = None,
    ):
        dataset_id = dataset_id or LOAN_DATASET.id
        dataset = (
            self.dataset_service.get_version(dataset_id, dataset_version)
            if dataset_version is not None
            else self.dataset_service.latest_published(dataset_id)
        )
        selected = EVALUATORS if evaluator_ids is None else tuple(
            item for item in EVALUATORS if item.id in evaluator_ids
        )
        if not selected:
            raise ValueError("at least one evaluator is required")
        unknown = set(evaluator_ids or ()) - {item.id for item in EVALUATORS}
        if unknown:
            raise ValueError(f"unknown evaluators: {', '.join(sorted(unknown))}")

        judge_model, identity = self._judge_model(judge_credential)
        selected = self._with_judge_identity(selected, identity)
        return self.engine.run(
            dataset, LoanAgent(self.repository), version, evaluators=selected,
            context=EvaluationContext(judge_client=judge_model),
            credentials=self.credentials,
        )

    def overview(self) -> dict:
        runs = self.repository.list_runs()
        completed = [run for run in runs if run.status == "completed"]
        latest = self.engine.report(runs[0].id) if runs else None
        case_count = sum(
            len(version.cases)
            for dataset in self.dataset_service.list_datasets()
            if (version := self.repository.get_latest_dataset_version(dataset.id)) is not None
        )
        return {
            "total_runs": len(runs),
            "completed_runs": len(completed),
            "case_count": case_count,
            "latest": latest,
        }

    def run_detail(self, run_id: str):
        return self.engine.report(run_id)

    def trace(self, run_id: str, case_id: str):
        return self.repository.get_trace(run_id, case_id)

    def versions(self) -> list[dict[str, str]]:
        return [
            {"id": version, "label": VERSION_LABELS.get(version, version)}
            for version in LoanAgent.versions
        ]

    def datasets(self) -> list[dict]:
        summaries = []
        for dataset in self.dataset_service.list_datasets():
            latest = self.repository.get_latest_dataset_version(dataset.id)
            draft = self.repository.get_dataset_draft(dataset.id)
            summaries.append({
                **dataset.model_dump(mode="json"),
                "version": latest.version if latest else None,
                "case_count": len(latest.cases) if latest else 0,
                "has_draft": draft is not None,
            })
        return summaries

    def evaluators(self) -> list[dict]:
        return [
            {
                "id": item.id,
                "name": item.name,
                "kind": item.kind,
                "version": item.version,
                "dimension": item.dimension,
                "metric": item.metric,
                "severity": item.severity,
                "execution_phase": item.execution_phase,
                "evaluator_type": item.evaluator_type,
                "operator": getattr(item, "operator", None),
                "prerequisites": [
                    {"evaluator_id": ref.evaluator_id, "policy": ref.policy}
                    for ref in item.prerequisites
                ],
                # Descriptive only; a credential_ref is a reference, never a key.
                "judge": {
                    "provider": item.judge.provider,
                    "model": item.judge.model,
                    "samples": item.judge.samples,
                    "input_selection": item.judge.input_selection,
                    "credential_ref": item.judge.credential_ref,
                } if isinstance(item, LlmJudgeEvaluatorSpec) else None,
            }
            for item in EVALUATORS
        ]
