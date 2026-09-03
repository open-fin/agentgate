from agentgate.control_plane import EvaluationService
from agentgate.storage.sqlite import SQLiteRepository


def test_risky_fails_and_fixed_improves(tmp_path):
    repository = SQLiteRepository(tmp_path / "demo.db")
    service = EvaluationService(repository)
    risky = service.launch("loan-agent-v1-risky")
    fixed = service.launch("loan-agent-v2-fixed")
    risky_report = service.run_detail(risky.id)
    fixed_report = service.run_detail(fixed.id)
    assert risky_report.gate.outcome == "fail"
    assert risky_report.gate.failed >= 3
    assert fixed_report.gate.outcome == "pass"
    assert fixed_report.gate.score > risky_report.gate.score
    assert len(repository.list_traces(risky.id)) == 2
    assert len(repository.list_results(fixed.id)) == 16
    failures = [result for result in risky_report.results if result.outcome == "fail"]
    assert all(result.primary_failure_step for result in failures)
    assert repository.get_business_state("loan", "A-100") is not None


def test_the_demo_judges_the_fixed_version_with_no_configuration(tmp_path):
    """A fresh checkout exercises the whole judge path: no endpoint, no key."""
    repository = SQLiteRepository(tmp_path / "judge.db")
    service = EvaluationService(repository)
    fixed = service.launch("loan-agent-v2-fixed")
    judged = next(
        item for item in service.run_detail(fixed.id).results
        if item.evaluator_id == "answer-quality"
    )
    assert judged.outcome == "pass"
    assert judged.evaluator_kind == "llm_judge"
    evidence = judged.judge_evidence
    assert evidence.resolved_model == "agentgate-demo-judge"
    assert evidence.prompt_sha256 and evidence.rubric_sha256
    assert dict(evidence.votes) == {"pass": 1}


def test_selecting_an_unconfigured_judge_credential_is_rejected(tmp_path):
    import pytest

    service = EvaluationService(SQLiteRepository(tmp_path / "cred.db"))
    assert [item["available"] for item in service.judge_credentials()] == [False, False]
    with pytest.raises(ValueError, match="unknown judge credential"):
        service.launch("loan-agent-v2-fixed", judge_credential="nope")
    with pytest.raises(ValueError, match="AGENTGATE_JUDGE_ENDPOINT"):
        service.launch("loan-agent-v2-fixed", judge_credential="public")


def test_a_selected_credential_is_recorded_in_run_provenance(monkeypatch, tmp_path):
    """The snapshot must name the judge that actually ran, not the demo default."""
    import json
    import urllib.request

    monkeypatch.setenv("AGENTGATE_JUDGE_API_KEY", "sk-live-key")
    monkeypatch.setenv("AGENTGATE_JUDGE_ENDPOINT", "https://api.example/v1/chat")
    monkeypatch.setenv("AGENTGATE_JUDGE_MODEL", "gpt-4o-mini")

    class Response:
        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    sent = []

    def fake_urlopen(request, timeout=None):
        sent.append(request)
        response = Response()
        response.read = lambda: json.dumps({
            "id": "x", "model": "gpt-4o-mini-2026",
            "choices": [{"message": {"content": json.dumps({
                "verdict": "pass", "score": 1.0, "confidence": 1.0, "reason": "ok",
            })}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }).encode()
        return response

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    repository = SQLiteRepository(tmp_path / "live.db")
    service = EvaluationService(repository)
    run = service.launch("loan-agent-v2-fixed", judge_credential="public")

    judge = next(
        item for item in run.snapshot.evaluator_specs if item.kind == "llm_judge"
    )
    assert judge.judge.provider == "openai_compatible"
    assert judge.judge.model == "gpt-4o-mini"
    assert judge.judge.credential_ref == "env:AGENTGATE_JUDGE_API_KEY"
    assert sent and sent[0].headers["Authorization"] == "Bearer sk-live-key"
    # The secret is referenced, never stored.
    assert "sk-live-key" not in run.model_dump_json()

    result = next(
        item for item in repository.list_results(run.id)
        if item.evaluator_id == "answer-quality"
    )
    assert result.judge_evidence.resolved_model == "gpt-4o-mini-2026"


def test_no_judge_credential_catalogue_entry_exposes_a_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTGATE_JUDGE_API_KEY", "sk-should-never-appear")
    service = EvaluationService(SQLiteRepository(tmp_path / "secret.db"))
    catalogue = service.judge_credentials()
    assert catalogue[0]["available"] is True
    assert "sk-should-never-appear" not in str(catalogue)
