import json

from typer.testing import CliRunner

from agentgate.cli.application import app


def test_cli_runs_demo_with_a_selected_real_provider(monkeypatch, tmp_path):
    import urllib.request

    monkeypatch.setenv("AGENTGATE_JUDGE_API_KEY", "sk-test-key")
    monkeypatch.setenv("AGENTGATE_JUDGE_ENDPOINT", "https://api.example/v1/chat")
    monkeypatch.setenv("AGENTGATE_JUDGE_MODEL", "judge-model")

    class Response:
        def read(self):
            return json.dumps({
                "id": "judge-response", "model": "judge-model-2026",
                "choices": [{
                    "message": {"content": json.dumps({
                        "verdict": "pass", "score": 1.0,
                        "confidence": 1.0, "reason": "ok",
                    })},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    database = tmp_path / "cli.db"
    result = CliRunner().invoke(app, [
        "evaluate", "--version", "loan-agent-v2-fixed",
        "--database", str(database), "--judge-credential", "public",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "completed"
    assert payload["gate"]["outcome"] == "pass"
