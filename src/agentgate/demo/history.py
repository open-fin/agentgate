"""Import bundled, terminal local-demo history without executing or replacing it."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from importlib.resources import files
from pathlib import Path

from agentgate.domain import (
    EvaluationResult,
    EvaluationRun,
    SkillAnalysisReport,
    TargetDescriptor,
    Trace,
)
from agentgate.domain.evaluation_task import EvaluationTask
from agentgate.storage.sqlite import SQLiteRepository

# Storage order and allowed tables are deliberately fixed. Credentials are never imported.
TABLE_MODELS = {
    "agentgate_target_descriptors": TargetDescriptor,
    "agentgate_skill_analysis_reports": SkillAnalysisReport,
    "agentgate_runs": EvaluationRun,
    "agentgate_run_asset_refs": None,
    "agentgate_traces": Trace,
    "agentgate_results": EvaluationResult,
    "agentgate_evaluation_tasks": EvaluationTask,
    "agentgate_evaluation_task_runs": None,
}
_SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|\bsk-[A-Za-z0-9_-]{16,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bBearer\s+(?!local\b|\[redacted\])[^\s\"\\]{12,}",
    re.IGNORECASE,
)
_SECRET_FIELDS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "authorization",
    "encrypted_api_key",
    "client_secret",
    "session_token",
}


def _check_secrets(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in _SECRET_FIELDS and child not in (None, "", "local", "[redacted]"):
                raise ValueError("history contains credential material")
            _check_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _check_secrets(child)
    elif isinstance(value, str):
        if _SECRET.search(value):
            raise ValueError("history contains credential material")
        # Judge evidence and SDK attributes sometimes contain nested JSON strings.
        if value.lstrip().startswith(("{", "[")):
            try:
                nested = json.loads(value)
            except ValueError:
                return
            _check_secrets(nested)


def _validate_payload(table: str, row: dict) -> None:
    model = TABLE_MODELS[table]
    if model is None:
        return
    payload = json.loads(row["payload"])
    _check_secrets(payload)
    record = model.model_validate(payload)
    for key in (
        "run_id",
        "case_id",
        "evaluator_id",
        "target_descriptor_sha256",
        "content_sha256",
        "status",
        "user_team_id",
    ):
        if key in row and hasattr(record, key) and row[key] != getattr(record, key):
            raise ValueError("history payload/index mismatch")
    if "id" in row:
        identity = record.trace_id if table == "agentgate_traces" else record.id
        if row["id"] != identity:
            raise ValueError("history identity mismatch")
    if isinstance(record, EvaluationRun):
        if record.status not in {"completed", "failed", "cancelled"}:
            raise ValueError("history requires terminal runs")
        if row["status"] != record.status or row["api_key"] is not None or record.api_key:
            raise ValueError("history run status or credentials are invalid")
        if record.user_team_id or row["user_team_id"]:
            raise ValueError("in-bank team records cannot be bundled")
        source = record.manifest.target.ref.source_id
        if source not in {"agentgate-demo", "local-bank-runtime"} and not source.startswith(
            "platform-mock-"
        ):
            raise ValueError("history requires a local demo target")


def _compatible(table: str, existing: dict, incoming: dict) -> bool:
    """Mutable display/ownership fields never overwrite the receiver's values."""
    if "payload" not in incoming:
        return existing == incoming
    left, right = (json.loads(r["payload"]) for r in (existing, incoming))
    ignored = {
        "agentgate_target_descriptors": {"fetched_at"},
        "agentgate_evaluation_tasks": {"name", "static_report_ids", "credential_id"},
        "agentgate_runs": {"user_id", "user_name", "api_key"},
    }.get(table, set())
    return {k: v for k, v in left.items() if k not in ignored} == {
        k: v for k, v in right.items() if k not in ignored
    }


def ensure_demo_history(
    database_path: str | Path,
    *,
    external_mode: bool,
    archive: bytes | None = None,
) -> dict[str, int]:
    """Atomically insert absent history rows; reject conflicts instead of overwriting."""
    if not external_mode:
        return {}
    compressed = (
        archive
        if archive is not None
        else files("agentgate.demo").joinpath("loan-history.json.gz").read_bytes()
    )
    bundle = json.loads(gzip.decompress(compressed))
    if bundle.get("format_version") != 1 or set(bundle["tables"]) != set(TABLE_MODELS):
        raise ValueError("unsupported demo history archive")
    SQLiteRepository(database_path).close()
    counts = {}
    with closing(sqlite3.connect(str(database_path), timeout=30)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE IF NOT EXISTS agentgate_demo_history_imports "
            "(archive_sha256 TEXT PRIMARY KEY, imported_at TEXT NOT NULL)"
        )
        digest = hashlib.sha256(compressed).hexdigest()
        if db.execute(
            "SELECT 1 FROM agentgate_demo_history_imports WHERE archive_sha256=?", (digest,)
        ).fetchone():
            return {table: 0 for table in TABLE_MODELS}
        for table in TABLE_MODELS:
            definition = db.execute(f"PRAGMA table_info({table})").fetchall()
            columns = [r["name"] for r in definition]
            primary = [r["name"] for r in sorted(definition, key=lambda r: r["pk"]) if r["pk"]]
            content = bundle["tables"][table]
            if content["columns"] != columns:
                raise ValueError(f"history schema mismatch: {table}")
            counts[table] = 0
            for values in content["rows"]:
                if len(values) != len(columns):
                    raise ValueError("history row width mismatch")
                row = dict(zip(columns, values, strict=True))
                _validate_payload(table, row)
                where = " AND ".join(f"{key}=?" for key in primary)
                old = db.execute(
                    f"SELECT * FROM {table} WHERE {where}", [row[key] for key in primary]
                ).fetchone()
                if old is not None:
                    if not _compatible(table, dict(old), row):
                        raise ValueError(f"history conflicts with existing data: {table}")
                    continue
                db.execute(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES "
                    f"({','.join('?' for _ in columns)})",
                    values,
                )
                counts[table] += 1
        # These references also live inside immutable JSON, outside SQLite foreign keys.
        for values in bundle["tables"]["agentgate_evaluation_tasks"]["rows"]:
            task = EvaluationTask.model_validate_json(values[-1])
            linked = {
                r[0]
                for r in db.execute(
                    "SELECT run_id FROM agentgate_evaluation_task_runs WHERE task_id=?", (task.id,)
                )
            }
            if linked != set(task.run_ids):
                raise ValueError("history task/run association mismatch")
            for report_id in task.static_report_ids:
                if not db.execute(
                    "SELECT 1 FROM agentgate_skill_analysis_reports WHERE id=?", (report_id,)
                ).fetchone():
                    raise ValueError("history static report is missing")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("history references are incomplete")
        db.execute(
            "INSERT INTO agentgate_demo_history_imports VALUES (?,datetime('now'))", (digest,)
        )
    return counts
