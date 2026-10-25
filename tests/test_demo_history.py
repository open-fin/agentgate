import gzip
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter
from importlib.resources import files

import pytest

from agentgate.application.result_reader import ResultReader
from agentgate.demo.history import ensure_demo_history
from agentgate.storage.sqlite import SQLiteRepository


def archive():
    return json.loads(
        gzip.decompress(files("agentgate.demo").joinpath("loan-history.json.gz").read_bytes())
    )


def compressed(bundle):
    return gzip.compress(json.dumps(bundle).encode(), mtime=0)


def test_fresh_history_preserves_single_ab_scores_traces_and_failures(tmp_path):
    path = tmp_path / "fresh.db"
    counts = ensure_demo_history(path, external_mode=True)
    assert counts["agentgate_evaluation_tasks"] == 43
    repo = SQLiteRepository(path)
    assert Counter(t.kind for t in repo.list_evaluation_tasks()) == {"single": 31, "ab": 12}
    runs = repo.list_runs(limit=1000, user_team_id="")
    assert Counter(r.status for r in runs) == {"completed": 49, "failed": 6}
    assert all(r.api_key is None for r in runs)
    assert all(t.name.startswith("历史验收 · ") for t in repo.list_evaluation_tasks())
    reader = ResultReader(repo)
    for run in runs:
        if run.status == "completed":
            assert reader.get_report(run.id).run.id == run.id
    comparison = reader.compare_runs(
        "d9e73e75-9411-49e3-b356-f98f9c4d8b14", "e91fb02f-e6bd-41c3-ac3f-189a5bc5d58a"
    )
    assert comparison.overall_score_delta == pytest.approx(0.0859138587208763)
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from agentgate_traces").fetchone()[0] == 391
        assert db.execute("select count(*) from agentgate_results").fetchone()[0] == 1776
        assert db.execute("select count(*) from agentgate_api_keys").fetchone()[0] == 0
        assert db.execute("pragma foreign_key_check").fetchall() == []


def test_repeat_start_preserves_edits_and_does_not_restore_deleted_tasks(tmp_path):
    path = tmp_path / "existing.db"
    ensure_demo_history(path, external_mode=True)
    repo = SQLiteRepository(path)
    tasks = repo.list_evaluation_tasks()
    repo.save_evaluation_task(tasks[0].model_copy(update={"name": "User renamed this task"}))
    repo.delete_task_record(tasks[1].id, user_team_id="")
    assert sum(ensure_demo_history(path, external_mode=True).values()) == 0
    assert repo.get_evaluation_task(tasks[0].id).name == "User renamed this task"
    assert repo.get_evaluation_task(tasks[1].id) is None


def test_first_import_preserves_existing_task_name_and_run_owner(tmp_path):
    path = tmp_path / "existing.db"
    ensure_demo_history(path, external_mode=True)
    repo = SQLiteRepository(path)
    task = repo.list_evaluation_tasks()[0]
    repo.save_evaluation_task(task.model_copy(update={"name": "Keep my task name"}))
    run = repo.get_run(task.run_ids[0])
    with sqlite3.connect(path) as db:
        # Represent a recipient's pre-existing owner; terminal runs cannot be edited via the API.
        db.execute(
            "update agentgate_runs set user_name=?, payload=? where id=?",
            (
                "Local user edit",
                run.model_copy(update={"user_name": "Local user edit"}).model_dump_json(),
                run.id,
            ),
        )
        db.execute("delete from agentgate_demo_history_imports")
    assert sum(ensure_demo_history(path, external_mode=True).values()) == 0
    assert repo.get_evaluation_task(task.id).name == "Keep my task name"
    assert repo.get_run(run.id).user_name == "Local user edit"


@pytest.mark.parametrize("mutation", ["active", "secret", "index", "missing_link"])
def test_bad_archive_is_atomic_and_never_activates_history(tmp_path, mutation):
    path = tmp_path / "bad.db"
    bundle = archive()
    table = bundle["tables"]["agentgate_runs"]
    row = table["rows"][-1]
    index = table["columns"].index("payload")
    payload = json.loads(row[index])
    if mutation == "active":
        payload.update(status="pending", started_at=None, completed_at=None, error=None)
        row[table["columns"].index("status")] = "pending"
    elif mutation == "secret":
        payload["api_key"] = "unpublishable-test-credential"
    elif mutation == "index":
        row[table["columns"].index("status")] = (
            "failed" if payload["status"] == "completed" else "completed"
        )
    else:
        bundle["tables"]["agentgate_evaluation_task_runs"]["rows"].pop()
    row[index] = json.dumps(payload)
    with pytest.raises(ValueError):
        ensure_demo_history(path, external_mode=True, archive=compressed(bundle))
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from agentgate_runs").fetchone()[0] == 0
        assert db.execute("select count(*) from agentgate_target_descriptors").fetchone()[0] == 0


def test_conflicting_results_are_not_overwritten(tmp_path):
    path = tmp_path / "conflict.db"
    ensure_demo_history(path, external_mode=True)
    bundle = archive()
    table = bundle["tables"]["agentgate_results"]
    index = table["columns"].index("payload")
    payload = json.loads(table["rows"][0][index])
    payload["reason"] = "Tampered historical reason"
    table["rows"][0][index] = json.dumps(payload)
    with pytest.raises(ValueError, match="conflicts"):
        ensure_demo_history(path, external_mode=True, archive=compressed(bundle))
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from agentgate_demo_history_imports").fetchone()[0] == 1
        assert not db.execute(
            "select 1 from agentgate_results where payload like '%Tampered historical reason%'"
        ).fetchall()


def test_inbank_mode_never_reads_or_imports_demo_archive(tmp_path):
    path = tmp_path / "inbank.db"
    assert ensure_demo_history(path, external_mode=False, archive=b"invalid") == {}
    assert not path.exists()
    env = {
        **os.environ,
        "AGENTGATE_AGENT_PLATFORM_MODE": "inbank",
        "AGENTGATE_DB_TYPE": "sqlite",
        "AGENTGATE_DB": str(path),
    }
    result = subprocess.run(
        [sys.executable, "scripts/seed-loan-evaluators.py"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not path.exists()


def test_standard_local_seed_shows_history_without_model_or_dispatch(tmp_path):
    path = tmp_path / "local.db"
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTGATE_JUDGE_")}
    env.update(
        AGENTGATE_AGENT_PLATFORM_MODE="mock",
        AGENTGATE_DB_TYPE="sqlite",
        AGENTGATE_DB=str(path),
        AGENT_TASK_DISPATCHER_TYPE="celery",
    )
    result = subprocess.run(
        [sys.executable, "scripts/seed-loan-evaluators.py"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    repo = SQLiteRepository(path)
    assert len(repo.list_evaluation_tasks()) == 43
    assert all(
        r.status in {"completed", "failed"} for r in repo.list_runs(limit=1000, user_team_id="")
    )
