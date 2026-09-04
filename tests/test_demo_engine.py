from agentgate.control_plane import EvaluationService
from agentgate.domain import Kind
from agentgate.evaluator import EVALUATORS
from agentgate.storage.sqlite import SQLiteRepository

RULE_IDS = [item.id for item in EVALUATORS if item.kind == Kind.RULE]


def test_risky_fails_and_fixed_improves(tmp_path):
    repository = SQLiteRepository(tmp_path / "demo.db")
    service = EvaluationService(repository)
    risky = service.launch("loan-agent-v1-risky", evaluator_ids=RULE_IDS)
    fixed = service.launch("loan-agent-v2-fixed", evaluator_ids=RULE_IDS)
    risky_report = service.run_detail(risky.id)
    fixed_report = service.run_detail(fixed.id)
    assert risky_report.gate.outcome == "fail"
    assert risky_report.gate.failed >= 3
    assert fixed_report.gate.outcome == "pass"
    assert fixed_report.gate.score > risky_report.gate.score
    assert len(repository.list_traces(risky.id)) == 5
    assert len(repository.list_results(fixed.id)) == 35
    failures = [result for result in risky_report.results if result.outcome == "fail"]
    assert all(result.primary_failure_step for result in failures)
    assert repository.get_business_state("loan", "A-100") is not None


def test_a_run_can_select_independent_cases(tmp_path):
    repository = SQLiteRepository(tmp_path / "selected-cases.db")
    service = EvaluationService(repository)
    run = service.launch(
        "loan-agent-v2-fixed",
        evaluator_ids=RULE_IDS,
        case_ids=["complaint-standard", "credit-inquiry-standard"],
    )
    assert run.snapshot.selected_case_ids == (
        "complaint-standard", "credit-inquiry-standard",
    )
    # The immutable Dataset snapshot remains the complete published version.
    assert len(run.snapshot.dataset.cases) == 5
    assert len(repository.list_traces(run.id)) == 2
    assert len(repository.list_results(run.id)) == 14


def test_case_selection_rejects_empty_unknown_and_duplicate_ids(tmp_path):
    import pytest

    service = EvaluationService(SQLiteRepository(tmp_path / "invalid-cases.db"))
    for case_ids, message in (
        ([], "at least one Case"),
        (["missing"], "unknown Cases"),
        (["complaint-standard", "complaint-standard"], "must be unique"),
    ):
        with pytest.raises(ValueError, match=message):
            service.launch(
                "loan-agent-v2-fixed", evaluator_ids=RULE_IDS, case_ids=case_ids,
            )


def test_selecting_an_unconfigured_judge_credential_is_rejected(tmp_path):
    import pytest

    service = EvaluationService(SQLiteRepository(tmp_path / "cred.db"))
    assert [item["available"] for item in service.judge_credentials()] == [False, False]
    with pytest.raises(ValueError, match="judge_credential is required"):
        service.launch("loan-agent-v2-fixed")
    with pytest.raises(ValueError, match="unknown judge credential"):
        service.launch("loan-agent-v2-fixed", judge_credential="nope")
    with pytest.raises(ValueError, match="AGENTGATE_JUDGE_ENDPOINT"):
        service.launch("loan-agent-v2-fixed", judge_credential="public")


def test_a_selected_credential_is_recorded_in_run_provenance(monkeypatch, tmp_path):
    """The snapshot must name the real Judge provider selected for the Run."""
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
