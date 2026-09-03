import pytest
from fastapi.testclient import TestClient

from agentgate.server.application import create_app


def test_config_catalogs_and_real_report_metrics(tmp_path):
    with TestClient(create_app(tmp_path / "metrics.db")) as client:
        datasets = client.get("/api/datasets").json()
        evaluators = client.get("/api/evaluators").json()
        assert len(datasets) == 1
        assert datasets[0]["id"] == "loan-risk-policy"
        assert datasets[0]["version"] == 1
        assert datasets[0]["case_count"] == 2
        assert datasets[0]["has_draft"] is False
        assert len(evaluators) == 8
        assert {item["kind"] for item in evaluators} == {"rule", "llm_judge"}
        assert {item["dimension"] for item in evaluators} == {
            "routing", "tool_use", "state", "answer", "safety",
        }
        judge = next(item for item in evaluators if item["kind"] == "llm_judge")
        assert judge["id"] == "answer-quality"
        assert judge["execution_phase"] == "llm_judge"
        assert judge["prerequisites"] == [
            {"evaluator_id": "policy-compliance", "policy": "on_pass_or_review"}
        ]
        assert judge["judge"]["samples"] == 1
        assert all(item["judge"] is None for item in evaluators if item["kind"] == "rule")

        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v1-risky", "dataset_id": "loan-risk-policy",
            "dataset_version": 1,
            "evaluator_ids": ["required-tool", "forbidden-tool", "tool-arguments"],
        })
        assert response.status_code == 201
        report = client.get(f"/api/runs/{response.json()['id']}").json()
        assert len(report["results"]) == 6  # 3 evaluators over 2 cases
        metrics = {(item["level"], item["key"]): item for item in report["metrics"]}
        assert metrics[("metric", "tool_coverage")]["score"] == 0.75  # 0.5, 1.0
        assert metrics[("metric", "forbidden_tool_compliance")]["score"] == 0.0
        assert metrics[("metric", "tool_argument_accuracy")]["score"] == 1.0
        # A dimension averages its metrics, not its raw results: (0.75+0+1)/3.
        assert metrics[("dimension", "tool_use")]["label"] == "工具准确率"
        assert metrics[("dimension", "tool_use")]["score"] == pytest.approx(7 / 12)
        assert metrics[("overall", "overall")]["score"] == pytest.approx(7 / 12)


def test_launch_rejects_empty_evaluator_selection(tmp_path):
    with TestClient(create_app(tmp_path / "invalid.db")) as client:
        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v2-fixed",
            "dataset_id": "loan-risk-policy",
            "dataset_version": 1,
            "evaluator_ids": [],
        })
        assert response.status_code == 422
