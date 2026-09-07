import json
import urllib.request

from fastapi.testclient import TestClient

from agentgate.server.application import create_app


def test_api_evaluation_and_persisted_trace(tmp_path):
    with TestClient(create_app(tmp_path / "api.db")) as client:
        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v1-risky",
            "dataset_id": "loan-agent-demo",
            "dataset_version": 1,
            "evaluator_ids": ["policy-compliance"],
        })
        assert response.status_code == 201
        run_id = response.json()["id"]
        report = client.get(f"/api/runs/{run_id}").json()
        assert report["gate"]["outcome"] == "fail"
        trace = client.get(f"/api/runs/{run_id}/traces/high-risk-approval")
        assert trace.status_code == 200
        assert any(span["name"] == "approve_loan" for span in trace.json()["spans"])


def test_api_launch_requires_an_explicit_dataset_version(tmp_path):
    with TestClient(create_app(tmp_path / "explicit-version.db")) as client:
        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v2-fixed",
            "dataset_id": "loan-agent-demo",
        })
        assert response.status_code == 422


def test_api_reports_missing_evaluator_prerequisite_as_configuration_error(tmp_path):
    with TestClient(create_app(tmp_path / "missing-prerequisite.db")) as client:
        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v2-fixed",
            "dataset_id": "loan-agent-demo",
            "dataset_version": 1,
            "evaluator_ids": ["answer-quality"],
            "judge_provider": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "api_key": "sk-test-only",
            },
        })

    assert response.status_code == 422
    assert response.json()["detail"] == "评估器配置缺少依赖项：policy-compliance"


def test_web_can_supply_a_request_scoped_judge_provider(monkeypatch, tmp_path):
    secret = "sk-browser-only"
    sent = []

    class Response:
        def __init__(self, verdict):
            self.verdict = verdict

        def read(self):
            return json.dumps({
                "id": "judge-web", "model": "deepseek-v4-pro",
                "choices": [{"message": {"content": json.dumps({
                    "verdict": self.verdict,
                    "score": 0.0 if self.verdict == "fail" else 1.0,
                    "confidence": 1.0, "reason": self.verdict,
                })}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        sent.append(request)
        payload = json.loads(request.data)
        material = payload["messages"][-1]["content"]
        return Response("fail" if "款项将于 3 个工作日内到账" in material else "pass")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with TestClient(create_app(tmp_path / "inline.db")) as client:
        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v3-misleading",
            "dataset_id": "loan-agent-demo",
            "dataset_version": 1,
            "case_ids": ["high-risk-approval"],
            "evaluator_ids": ["policy-compliance", "answer-quality"],
            "judge_provider": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "api_key": secret,
            },
        })
        assert response.status_code == 201
        report = client.get(f"/api/runs/{response.json()['id']}").json()

    judge = next(
        item for item in report["run"]["snapshot"]["evaluator_specs"]
        if item["id"] == "answer-quality"
    )
    assert judge["severity"] == "blocking"
    assert judge["judge"]["provider"] == "deepseek"
    assert judge["judge"]["model"] == "deepseek-v4-pro"
    assert judge["judge"]["credential_ref"] is None
    assert report["run"]["snapshot"]["selected_case_ids"] == ["high-risk-approval"]
    assert sent and all(item.headers["Authorization"] == f"Bearer {secret}" for item in sent)
    assert secret not in json.dumps(report)
    assert report["gate"]["outcome"] == "fail"
    assert report["gate"]["reason"] == "阻断级检查失败"


def test_otlp_http_uses_post_and_health_is_separate(tmp_path):
    payload = {"resourceSpans": [{"resource": {"attributes": [
        {"key": "agentgate.run_id", "value": {"stringValue": "external-run"}},
        {"key": "agentgate.case_id", "value": {"stringValue": "external-case"}},
    ]}, "scopeSpans": [{"spans": [{"traceId": "abc", "spanId": "def", "name": "tool.call",
                                      "attributes": [{"key": "agentgate.kind", "value": {"stringValue": "tool"}}]}]}]}]}
    with TestClient(create_app(tmp_path / "otlp.db")) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/v1/traces").status_code == 405
        response = client.post("/v1/traces", json=payload)
        assert response.status_code == 202
        assert response.json() == {"accepted_spans": 1}
        stored = client.app.state.repository.get_trace("external-run", "external-case")
        assert stored is not None and stored.spans[0].name == "tool.call"
