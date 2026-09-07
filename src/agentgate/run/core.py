from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from agentgate.domain import (
    Case, DatasetVersion, DatasetVersionStatus, GateSpec, MetricPlan, Run, RunSnapshot,
    RunStatus, TargetSnapshot, Trace,
)
from agentgate.evaluator import (
    EVALUATORS, EvaluationContext, evaluate_case, validate_evaluation_plan,
)
from agentgate.evaluator.judge import CredentialChecker
from agentgate.result.service import build_report
from agentgate.storage.base import AgentGateRepository


class Target(Protocol):
    def execute(self, run_id: str, case: Case, version: str) -> Trace: ...


class ExternalSchedulerAdapter(Protocol):
    def execute(self, target: Target, run_id: str, case: Case, version: str) -> Trace: ...


class LocalScheduler:
    def execute(self, target: Target, run_id: str, case: Case, version: str) -> Trace:
        return target.execute(run_id, case, version)


class PythonFunctionTarget:
    def __init__(self, function) -> None:
        self.function = function

    def execute(self, run_id: str, case: Case, version: str) -> Trace:
        return self.function(run_id, case, version)


class RunEngine:
    def __init__(
        self, repository: AgentGateRepository,
        scheduler: ExternalSchedulerAdapter | None = None,
    ) -> None:
        self.repository = repository
        self.scheduler = scheduler or LocalScheduler()

    def run(
        self, dataset: DatasetVersion, target: Target, target_version: str,
        provider: str = "deterministic", evaluators=EVALUATORS,
        context: EvaluationContext | None = None,
        credentials: CredentialChecker | None = None,
        case_ids: tuple[str, ...] | None = None,
    ) -> Run:
        if dataset.status != DatasetVersionStatus.PUBLISHED:
            raise ValueError("only published Dataset versions can be evaluated")
        selected = tuple(evaluators)
        available = {case.id: case for case in dataset.cases}
        selected_case_ids = tuple(available) if case_ids is None else case_ids
        if not selected_case_ids:
            raise ValueError("at least one Case is required")
        if len(selected_case_ids) != len(set(selected_case_ids)):
            raise ValueError("selected Case ids must be unique")
        unknown_cases = set(selected_case_ids) - set(available)
        if unknown_cases:
            raise ValueError(f"unknown Cases: {', '.join(sorted(unknown_cases))}")
        # Dataset order is stable regardless of the order submitted by a UI.
        selected_case_id_set = set(selected_case_ids)
        selected_cases = tuple(
            case for case in dataset.cases if case.id in selected_case_id_set
        )
        selected_case_ids = tuple(case.id for case in selected_cases)
        validation_dataset = DatasetVersion.model_validate({
            **dataset.model_dump(mode="json"),
            "cases": selected_cases,
            "content_sha256": "",
        })
        validate_evaluation_plan(validation_dataset, selected, credentials)
        snapshot = RunSnapshot(
            dataset=dataset,
            selected_case_ids=selected_case_ids,
            target=TargetSnapshot(
                name="loan-agent", version=target_version, provider=provider
            ),
            evaluator_specs=selected,
            primary_evaluator_ids=tuple(item.id for item in selected),
            metric_plan=MetricPlan(),
            gate_spec=GateSpec(),
        )
        run = Run(
            snapshot=snapshot,
            status=RunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        self.repository.save_run(run)
        results = []
        try:
            for case in selected_cases:
                trace = self.scheduler.execute(target, run.id, case, target_version)
                self.repository.save_trace(trace)
                results.extend(
                    evaluate_case(case, trace, snapshot.evaluator_specs, context)
                )
            self.repository.save_results(results)
            completed = run.model_copy(update={
                "status": RunStatus.COMPLETED,
                "completed_at": datetime.now(UTC),
            })
            self.repository.save_run(completed)
            return completed
        except Exception as exc:
            failed = run.model_copy(update={
                "status": RunStatus.FAILED,
                "completed_at": datetime.now(UTC),
                "error": str(exc),
            })
            self.repository.save_run(failed)
            raise

    def report(self, run_id: str):
        run = self.repository.get_run(run_id)
        if run is None:
            return None
        return build_report(run, self.repository.list_results(run_id))
