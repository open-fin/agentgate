"""Launch real HTTP evaluations against the local three-mode tested Agent."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentgate.domain import EvaluationRun, EvaluatorRef
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.integrations.targets.local_bank import LocalBankClient, local_bank_target
from agentgate.run.target_protocol import TargetExecutionError
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.user_context import get_user_info

router = APIRouter(prefix="/api", tags=["bank-targets"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class BankLaunch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    mode: Literal["base", "workflow", "cloudshrimp"]
    version: str = "v1"
    dataset_id: str
    dataset_version: int = Field(ge=1)
    case_ids: list[str] | None = None
    evaluator_ids: list[str] | None = None
    evaluator_refs: list[EvaluatorRef] | None = Field(default=None, min_length=1)
    timeout_seconds: float = Field(default=180, gt=0, le=300)
    repetitions: int = Field(default=1, ge=1, le=20, strict=True)
    scheduled_for: datetime | None = None
    target_descriptor_sha256: str | None = None

    @model_validator(mode="after")
    def validate_evaluator_selection(self) -> "BankLaunch":
        if self.evaluator_ids is not None and self.evaluator_refs is not None:
            raise ValueError("use evaluator_ids or evaluator_refs, not both")
        return self


@router.get("/bank-targets")
def list_targets(dependencies: Dependencies):
    client = LocalBankClient()
    try:
        records = []
        for record in client.call("/agents"):
            descriptor, snapshot = local_bank_target(client, record["mode"], record["agent_version"])
            dependencies.targets.register_descriptor(descriptor)
            records.append({"descriptor": descriptor, "snapshot": snapshot})
        return records
    except (TargetExecutionError, ValueError):
        raise HTTPException(503, "local bank runtime is unavailable or incompatible") from None


@router.post("/bank-evaluations", status_code=202)
def launch(request: BankLaunch, dependencies: Dependencies):
    try:
        descriptor, target = local_bank_target(LocalBankClient(), request.mode, request.version)
        if request.target_descriptor_sha256 and request.target_descriptor_sha256 != descriptor.content_sha256:
            raise ValueError("智能体配置已变化，请刷新后重新提交，不能静默替换所选版本")
        if request.repetitions > 1 and request.scheduled_for is not None:
            raise ValueError("稳定性测试暂不支持预约")
        dependencies.targets.register_descriptor(descriptor)
        selected_ids = request.evaluator_ids
        if selected_ids is None and request.evaluator_refs is None:
            selected_ids = ["final-state", "required-tool", "forbidden-tool"]
        run = dependencies.runs.create_run(target, dataset_id=request.dataset_id,
            dataset_version=request.dataset_version, case_ids=request.case_ids,
            evaluator_ids=selected_ids,
            evaluator_refs=request.evaluator_refs, timeout_seconds=request.timeout_seconds,
            max_parallel_cases=1, max_retries=0, scheduled_for=request.scheduled_for, persist=False)
        for case in run.manifest.execution_cases:
            if set(case.initial_state) - {"customer"}:
                raise ValueError("only test customer initial_state is supported")
            if case.initial_state.get("customer", "test-low") not in {"test-low", "test-high", "test-blocked"}:
                raise ValueError("unknown synthetic customer")
            for turn in case.turns:
                if set(turn.input) != {"txt"} or not isinstance(turn.input["txt"], str) or not 1 <= len(turn.input["txt"].strip()) <= 4000:
                    raise ValueError("bank turns require nonblank txt up to 4000 characters")
        runs = [run, *(EvaluationRun(manifest=run.manifest, user_team_id=run.user_team_id,
            user_id=run.user_id, user_name=run.user_name, api_key=run.api_key)
            for _ in range(request.repetitions - 1))]
        task = EvaluationTask(id=run.id, name=request.name.strip() if request.name else None, kind="stability" if request.repetitions > 1 else "single", run_ids=tuple(r.id for r in runs))
        dependencies.repository.save_task_runs(task, runs)
        for item in runs:
            if item.status == "scheduled":
                continue
            try:
                dependencies.runs.dispatch_run(item.id, dependencies.dispatcher)
            except RuntimeError:
                if request.repetitions == 1:
                    raise
        if request.repetitions > 1:
            return task
        return dependencies.results.get_run_progress(run.id)
    except TargetExecutionError:
        raise HTTPException(503, "local bank runtime is unavailable") from None
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, str(exc)) from None
    except RuntimeError:
        raise HTTPException(503, "evaluation dispatch failed") from None


class BankComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    mode: Literal["base", "workflow", "cloudshrimp"]
    baseline_version: str
    candidate_version: str
    baseline_descriptor_sha256: str
    candidate_descriptor_sha256: str
    dataset_id: str
    dataset_version: int = Field(ge=1)
    case_ids: list[str] | None = None
    evaluator_refs: list[EvaluatorRef] = Field(min_length=1)
    timeout_seconds: float = Field(default=300, gt=0, le=300)


@router.post("/bank-comparisons", status_code=202)
def compare_bank(request: BankComparison, dependencies: Dependencies,
                 authorization: str | None = Header(default=None)):
    """Local-only versioned execution; never use the in-bank session token."""
    if authorization != "Bearer local":
        raise HTTPException(403, "loan evolution experiments require external local mode")
    from agentgate.application.ab_testing import create_ab_runs
    try:
        client = LocalBankClient()
        targets = []
        for version, digest in ((request.baseline_version, request.baseline_descriptor_sha256),
                                (request.candidate_version, request.candidate_descriptor_sha256)):
            descriptor, target = local_bank_target(client, request.mode, version)
            if descriptor.content_sha256 != digest:
                raise ValueError("智能体版本定义已变化，请刷新后重新提交")
            dependencies.targets.register_descriptor(descriptor)
            targets.append(target)
        dataset = dependencies.runs.dataset_management.get_version(request.dataset_id, request.dataset_version)
        for case in dataset.cases:
            if set(case.initial_state) - {"customer"} or case.initial_state.get("customer", "test-low") not in {"test-low", "test-high", "test-blocked"}:
                raise ValueError("only registered synthetic customer initial state is supported")
            if any(set(t.input) != {"txt"} or not isinstance(t.input["txt"], str) or not 1 <= len(t.input["txt"].strip()) <= 4000 for t in case.turns):
                raise ValueError("bank turns require nonblank txt up to 4000 characters")
        pair = create_ab_runs(dependencies.runs, dependencies.dispatcher, *targets,
            dataset_id=request.dataset_id, dataset_version=request.dataset_version,
            evaluator_refs=request.evaluator_refs, case_ids=request.case_ids,
            name=request.name, timeout_seconds=request.timeout_seconds)
        return {"baseline": {"run_id": pair.baseline_run.id, "status": pair.baseline_run.status},
                "candidate": {"run_id": pair.candidate_run.id, "status": pair.candidate_run.status}}
    except TargetExecutionError:
        raise HTTPException(503, "local bank runtime unavailable") from None
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/runs/{run_id}/target-descriptor")
def run_target(run_id: str, dependencies: Dependencies):
    info = get_user_info()
    run = dependencies.repository.get_run(run_id, user_team_id=info.user_team_id if info else "")
    if run is None:
        raise HTTPException(404, "unknown run")
    descriptor = dependencies.repository.get_target_descriptor(run.manifest.target.descriptor_sha256)
    if descriptor is None:
        raise HTTPException(404, "missing pinned descriptor")
    return descriptor


@router.get("/model-runtime")
def model_runtime(dependencies: Dependencies):
    """Safe connection metadata; never expose credentials or claim live health."""
    import os
    from urllib.parse import urlsplit, urlunsplit
    raw = urlsplit(os.getenv("AGENTGATE_JUDGE_BASE_URL", ""))
    origin = urlunsplit((raw.scheme, raw.netloc.rsplit("@", 1)[-1], raw.path, "", ""))
    configured = dependencies._judge_client is not None
    rows = [{"role": role, "model": os.getenv("AGENTGATE_JUDGE_MODEL_ID", ""),
             "base_url": origin, "configured": configured, "connection_verified": False}
            for role in ("LLM 评估器默认连接", "Skill 静态分析", "调优根因分析")]
    try:
        agents = LocalBankClient().call("/agents", timeout=3)
        rows.extend({"role": "被测智能体 · " + a["mode"], "model": a["model"],
                     "base_url": "服务端管理", "configured": True, "connection_verified": False} for a in agents)
    except (ValueError, TargetExecutionError):
        rows.append({"role": "被测智能体服务", "model": "", "base_url": "服务不可达", "configured": False, "connection_verified": False})
    return {"connections": rows, "management": "server_environment"}
