"""Run state and immutable execution snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import Field, model_validator

from .base import DomainModel, FrozenJsonObject, content_sha256
from .case import DatasetVersion
from .evaluation import EvaluatorSpec
from .gate import GateSpec
from .metric import MetricPlan


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TargetSnapshot(DomainModel):
    name: str
    version: str
    provider: str
    config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)


class RunSnapshot(DomainModel):
    dataset: DatasetVersion
    #: Exact Dataset Case ids executed by this Run, in Dataset order.
    #: Empty is retained only for reading snapshots created before Case selection.
    selected_case_ids: tuple[str, ...] = ()
    target: TargetSnapshot
    evaluator_specs: tuple[EvaluatorSpec, ...]
    primary_evaluator_ids: tuple[str, ...]
    metric_plan: MetricPlan
    gate_spec: GateSpec
    created_at: datetime = Field(default_factory=utcnow)
    snapshot_sha256: str = ""

    @model_validator(mode="after")
    def set_or_verify_hash(self) -> "RunSnapshot":
        payload = self.model_dump(mode="json", exclude={"snapshot_sha256"})
        expected = content_sha256(payload)
        if self.snapshot_sha256 and self.snapshot_sha256 != expected:
            # Backward compatibility for snapshots persisted before
            # selected_case_ids became part of the hash.
            legacy_payload = dict(payload)
            legacy_payload.pop("selected_case_ids", None)
            if self.selected_case_ids or self.snapshot_sha256 != content_sha256(legacy_payload):
                raise ValueError("RunSnapshot content hash mismatch")
        if not self.snapshot_sha256:
            object.__setattr__(self, "snapshot_sha256", expected)
        return self

    @property
    def evaluators(self) -> tuple[EvaluatorSpec, ...]:
        return self.evaluator_specs


class Run(DomainModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: RunStatus = RunStatus.PENDING
    snapshot: RunSnapshot
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
