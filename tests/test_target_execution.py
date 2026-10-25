"""Real in-bank adapters execute persisted Runs through the shared engine."""

import json
import logging
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import unquote

import pytest
from test_run_engine import pending_run
from test_target_execution_factory import configure_inbank, target_snapshot

from agentgate.domain import (
    Case,
    CaseTurn,
    EvaluationRun,
    RunStatus,
    TargetSnapshot,
    transition_run,
)
from agentgate.integrations.job_dispatchers import execution
from agentgate.integrations.job_dispatchers.celery import execute_evaluation_run
from agentgate.integrations.targets.inbank import chatabc, yunxia
from agentgate.run.target_protocol import TargetExecutionError
from agentgate.storage.sqlite import SQLiteRepository


class RecordingTransport:
    """Return current adapter-contract fixtures without connecting to a bank."""

    def __init__(self):
        self.evidence = {}
        self.trace_fault = None
        self.query_count = 0
        self.created = 0
        self.create_requests = []
        self.deleted = 0
        self.delete_requests = []
        self.sessions = []
        self.messages = []
        self.fail_chat = False
        self.chat_error_event = False
        self.yunxia_auxiliary_events = False
        self.yunxia_error_event = False

    def request_json(self, method, url, *, payload=None, **kwargs):
        if "createAgent" in url:
            self.created += 1
            self.create_requests.append({"method": method, "url": url, "payload": payload})
            return {"code": "0000", "data": {"agentName": "test-pod"}}
        if "deleteAgent" in url or "delete_agent" in url:
            self.deleted += 1
            self.delete_requests.append(
                {"method": method, "url": url, "payload": payload}
            )
            if "/agent-manager/chatabc/delete_agent" in url:
                return {"resCode": "FAIAG0000"}
            return {"code": "0000"}
        if "health_check" in url:
            return {"data": {"status": "ok"}}
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/init_session"):
            session = f"session-{len(self.sessions)}"
            self.sessions.append(session)
            return {"resCode": "FAIAG0000", "data": {"session_id": session}}
        raise AssertionError(f"unexpected request: {method} {url}")

    def request_bytes(self, method, url, *, payload, headers, **kwargs):
        if self.fail_chat:
            raise TargetExecutionError("rejected", "test chat failed")
        if url.endswith("/chat"):
            self.messages.append(payload["data"])
            if self.chat_error_event:
                return (
                    "event: error\n"
                    'data: {"errorCode": "BASE-001", '
                    '"message": "customer base failed"}\n\n'
                ).encode()
            events = [("message", {"content": "answer", "node_id": "end",
                "additional_kwargs": {"node_id": "end", "node_output": "answer"}})]
        else:
            assert url.endswith("/api/v1/message")
            self.messages.append(payload)
            if self.yunxia_error_event:
                events = [("failed", {"message": "customer Yunxia failed"})]
            elif self.yunxia_auxiliary_events:
                events = [
                    ("chat_started", {"chat_id": "chat-1"}),
                    ("node_started", {"node_id": "intentClassification"}),
                    ("chunk", {"content": "partial"}),
                    ("message", {"status": "completed", "output": "answer"}),
                ]
            else:
                events = [
                    (
                        "start",
                        {
                            "request_id": headers["X-Request-ID"],
                            "session_id": payload["sessionId"],
                        },
                    ),
                    ("message", {"status": "completed", "output": "answer"}),
                    ("done", "[DONE]"),
                ]
            reference = self.trace_reference(payload, headers)
            events.insert(-1 if events[-1][0] == "done" else len(events), ("trace", reference))
            return "".join(
                f"event: {name}\ndata: "
                f"{data if data == '[DONE]' else json.dumps(data)}\n\n"
                for name, data in events
            ).encode()
        events.append(("trace", self.trace_reference(payload["data"], headers)))
        return (
            "".join(
                f"event: {name}\ndata: {json.dumps(data)}\n\n"
                for name, data in events
            )
            + "event: done\ndata: [DONE]\n\n"
        ).encode()


    def trace_reference(self, payload, headers):
        source = f"source-{len(self.messages)}"
        session = payload.get("session_id", payload.get("sessionId"))
        reference = {"project_id": "inbank-tests", "trace_id": source,
                     "session_id": session, "request_id": headers["X-Request-ID"]}
        detail = trace_detail(source, session, payload["txt"])
        if self.trace_fault == "session":
            detail["trace"]["sessionId"] = "different-session"
        elif self.trace_fault == "input":
            detail["trace"]["input"] = {"txt": "wrong turn"}
        elif self.trace_fault == "output":
            detail["trace"]["output"] = "wrong answer"
        elif self.trace_fault == "project":
            reference["project_id"] = "another-project"
        elif self.trace_fault == "missing":
            reference = {}
        elif self.trace_fault == "incomplete":
            detail["spans"].pop()
        self.evidence[source] = detail
        return reference


def trace_detail(source, session, text):
    start = "2026-10-08T00:00:00Z"
    root = {"id": source, "projectId": "inbank-tests", "sessionId": session,
            "name": "agent", "agentName": "test-pod", "input": {"txt": text},
            "output": "answer", "status": "success", "spanCount": 4,
            "durationMs": 5, "startedAt": start}
    spans = []
    for sid, parent, kind, name in [("root", None, "agent", "agent"),
                                   ("skill", "root", "chain", "skill.review"),
                                   ("llm", "skill", "llm", "model"),
                                   ("tool", "skill", "tool", "credit_inquiry")]:
        spans.append({"id": sid, "traceId": source, "eventId": sid,
                      "parentSpanId": parent, "spanType": kind, "name": name,
                      "toolName": name if kind == "tool" else None,
                      "status": "success", "durationMs": 1, "startedAt": start,
                      "input": {"txt": text}, "output": "answer"})
    return {"trace": root, "spans": spans, "observations": []}


@pytest.fixture
def trace_endpoint(monkeypatch):
    transport = RecordingTransport()
    monkeypatch.setenv("AGENTGATE_INBANK_TRACE_PROJECT_ID", "inbank-tests")
    monkeypatch.setenv("AGENTGATE_TRACE_SERVER_TOKEN", "trace-service-test-credential")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.headers.get("Authorization") == "Bearer trace-service-test-credential"
            transport.query_count += 1
            parts = self.path.split("/")
            assert parts[4] == "inbank-tests"
            source = unquote(parts[6])
            if transport.trace_fault == "unavailable":
                self.send_response(503)
                self.end_headers()
                return
            detail = transport.evidence[source]
            value = {"items": [{"eventId": "llm-request", "spanId": "llm",
                                "model": "test-model", "input": {"messages": []},
                                "output": "answer", "startedAt": "2026-10-08T00:00:00Z",
                                "status": "success"}]} if self.path.endswith("/llm_requests") else detail
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("AGENTGATE_TRACE_SERVER_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        yield transport
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(params=["inbank_chatabc", "inbank_workflow", "inbank_yunxia"])
def persisted_target(request, tmp_path, monkeypatch, trace_endpoint):
    adapter_type = "inbank_chatabc" if request.param == "inbank_workflow" else request.param
    configure_inbank(monkeypatch, adapter_type)
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "sqlite")
    monkeypatch.setenv("AGENTGATE_DB", str(tmp_path / "execution.db"))
    monkeypatch.setattr(execution, "load_judge_model_from_environment", lambda: None)
    transport = trace_endpoint
    module = chatabc if adapter_type == "inbank_chatabc" else yunxia
    monkeypatch.setattr(module, "_UrlLibTransport", lambda: transport)
    cases = tuple(
        Case(
            id=f"case-{index}",
            name=f"Case {index}",
            turns=(
                CaseTurn(id="first", input={"txt": "hello"}),
                CaseTurn(id="second", input={"txt": "continue"}),
            ),
        )
        for index in range(2)
    )
    target = target_snapshot(adapter_type)
    if request.param == "inbank_workflow":
        values = target.model_dump(exclude={"content_sha256"})
        values["invocation_config"] = {"arrange_type": "workflow"}
        target = TargetSnapshot(**values)
    original = pending_run(cases=cases, target=target)
    run = EvaluationRun(
        id="12345678-1234-1234-1234-abcdef987654",
        manifest=original.manifest,
    )
    with closing(SQLiteRepository(tmp_path / "execution.db")) as repository:
        repository.save_run(run)
        yield SimpleNamespace(repository=repository, run=run, transport=transport)


@pytest.mark.parametrize("entry", [execution.execute_persisted_run, execute_evaluation_run.run])
def test_persisted_run_produces_traces_results_and_cleans_pod(persisted_target, entry):
    context = persisted_target
    assert entry(context.run.id) == "completed"
    assert context.repository.get_run(context.run.id).status is RunStatus.COMPLETED
    traces = context.repository.list_traces(context.run.id)
    results = context.repository.list_results(context.run.id)
    assert len(traces) == len(results) == 2
    assert all(trace.final_output["output"] == "answer" for trace in traces)
    assert all(len(trace.turn_outcomes) == 2 for trace in traces)
    assert all(len(trace.spans) == 10 for trace in traces)
    assert all({s.operation_type for s in t.spans} >= {"llm", "tool", "chain", "turn"} for t in traces)
    assert all(any(s.events for s in t.spans if s.operation_type == "llm") for t in traces)
    assert all(s.attributes["inbank.evidence_mode"] == "trace_server" for t in traces for s in t.spans)
    assert context.transport.query_count == 8
    assert context.transport.created == context.transport.deleted == 1
    assert context.transport.create_requests == [
        {
            "method": "POST",
            "url": "http://bank.invalid/web/agent_endpoint/createAgent?taskId=ef987654",
            "payload": {
                "agentId": "loan-agent",
                "agentVersion": "loan-agent-v2-fixed",
                **(
                    {"branchId": "branch-review"}
                    if context.run.manifest.target.adapter_type == "inbank_yunxia"
                    else {}
                ),
            },
        }
    ]
    if context.run.manifest.target.adapter_type == "inbank_chatabc":
        assert context.transport.delete_requests == [
            {
                "method": "POST",
                "url": "http://bank.invalid/agent-api/agent-manager/chatabc/delete_agent",
                "payload": {
                    "appId": "",
                    "trCode": "",
                    "trVersion": "",
                    "timestamp": 1,
                    "requestId": "",
                    "data": {
                        "agent_name": "test-pod",
                        "agent_namespace": "chatabc",
                    },
                },
            }
        ]
    messages = context.transport.messages
    session_key = "session_id" if "session_id" in messages[0] else "sessionId"
    assert messages[0][session_key] == messages[1][session_key]
    assert messages[2][session_key] == messages[3][session_key]
    assert messages[0][session_key] != messages[2][session_key]
    assert entry(context.run.id) == "completed"
    assert context.transport.created == context.transport.deleted == 1
    assert context.repository.list_traces(context.run.id) == traces
    assert context.repository.list_results(context.run.id) == results


def test_execution_failure_cleans_pod_and_records_failed_run(persisted_target):
    context = persisted_target
    context.transport.fail_chat = True
    with pytest.raises(TargetExecutionError, match="test chat failed"):
        execution.execute_persisted_run(context.run.id)
    assert context.repository.get_run(context.run.id).status is RunStatus.FAILED
    assert context.transport.created == context.transport.deleted == 1


def test_yunxia_accepts_auxiliary_events_without_start_or_done(persisted_target):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_yunxia":
        pytest.skip("Yunxia-only SSE compatibility")
    context.transport.yunxia_auxiliary_events = True

    assert execution.execute_persisted_run(context.run.id) == "completed"
    assert context.repository.get_run(context.run.id).status is RunStatus.COMPLETED
    assert context.transport.created == context.transport.deleted == 1


def test_yunxia_still_rejects_failure_events(persisted_target):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_yunxia":
        pytest.skip("Yunxia-only SSE compatibility")
    context.transport.yunxia_error_event = True

    with pytest.raises(TargetExecutionError, match="returned an error event"):
        execution.execute_persisted_run(context.run.id)

    assert context.repository.get_run(context.run.id).status is RunStatus.FAILED
    assert context.transport.created == context.transport.deleted == 1


@pytest.mark.parametrize("debug_enabled", [False, True])
def test_chatabc_sse_error_diagnostics_are_opt_in(
    persisted_target, monkeypatch, caplog, debug_enabled
):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_chatabc":
        pytest.skip("ChatABC-only SSE diagnostics")
    context.transport.chat_error_event = True
    if debug_enabled:
        monkeypatch.setenv("AGENTGATE_INBANK_DEBUG_SSE_FAILURES", "1")
    else:
        monkeypatch.delenv("AGENTGATE_INBANK_DEBUG_SSE_FAILURES", raising=False)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(
            TargetExecutionError, match="customer chat returned an error event"
        ):
            execution.execute_persisted_run(context.run.id)

    assert ("inbank_sse_failure" in caplog.text) is debug_enabled
    assert ("BASE-001" in caplog.text) is debug_enabled
    assert ("customer base failed" in caplog.text) is debug_enabled
    assert context.transport.created == context.transport.deleted == 1


@pytest.mark.parametrize("debug_enabled", [False, True])
def test_yunxia_sse_error_diagnostics_are_opt_in(
    persisted_target, monkeypatch, caplog, debug_enabled
):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_yunxia":
        pytest.skip("Yunxia-only SSE diagnostics")
    context.transport.yunxia_error_event = True
    if debug_enabled:
        monkeypatch.setenv("AGENTGATE_INBANK_DEBUG_SSE_FAILURES", "1")
    else:
        monkeypatch.delenv("AGENTGATE_INBANK_DEBUG_SSE_FAILURES", raising=False)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(TargetExecutionError, match="customer chat returned"):
            execution.execute_persisted_run(context.run.id)

    assert ("inbank_sse_failure" in caplog.text) is debug_enabled
    assert ("customer Yunxia failed" in caplog.text) is debug_enabled
    assert context.transport.created == context.transport.deleted == 1


def test_cancelled_delivery_does_not_create_pod(persisted_target):
    context = persisted_target
    context.repository.save_run(transition_run(context.run, RunStatus.CANCELLED))
    assert execution.execute_persisted_run(context.run.id) == "cancelled"
    assert context.transport.created == context.transport.deleted == 0


def test_run_id_must_provide_an_eight_character_customer_task_id(persisted_target):
    context = persisted_target
    run = EvaluationRun(id="short", manifest=context.run.manifest)
    context.repository.save_run(run)

    with pytest.raises(TargetExecutionError, match="at least 8 characters"):
        execution.execute_persisted_run(run.id)

    assert context.transport.created == 0


def test_yunxia_requires_branch_before_creation(persisted_target):
    context = persisted_target
    if context.run.manifest.target.adapter_type != "inbank_yunxia":
        pytest.skip("Yunxia-only branch contract")
    values = context.run.manifest.target.model_dump(exclude={"content_sha256"})
    values["invocation_config"] = {"agent_version": "loan-agent-v2-fixed"}
    target = TargetSnapshot(**values)
    run = EvaluationRun(manifest=pending_run(target=target).manifest)
    context.repository.save_run(run)

    with pytest.raises(TargetExecutionError, match="branch_id is required"):
        execution.execute_persisted_run(run.id)

    assert context.transport.created == 0


@pytest.mark.parametrize("override", [{"max_retries": 1}, {"max_parallel_cases": 2}])
def test_invalid_execution_limits_are_rejected_before_creation(persisted_target, override):
    context = persisted_target
    run = pending_run(target=context.run.manifest.target, **override)
    run = EvaluationRun(manifest=run.manifest)
    context.repository.save_run(run)
    with pytest.raises(ValueError, match="no retries and serial cases"):
        execution.execute_persisted_run(run.id)
    assert context.transport.created == 0


def test_judge_initialization_failure_closes_target(persisted_target, monkeypatch):
    context = persisted_target
    module = chatabc if context.run.manifest.target.adapter_type == "inbank_chatabc" else yunxia
    adapter_class = (
        module.InbankChatABCTargetAdapter if module is chatabc else module.InbankYunxiaTargetAdapter
    )
    close = Mock()
    monkeypatch.setattr(adapter_class, "close", close)
    monkeypatch.setattr(
        execution,
        "load_judge_model_from_environment",
        Mock(side_effect=ValueError("invalid judge")),
    )
    with pytest.raises(ValueError, match="invalid judge"):
        execution.execute_persisted_run(context.run.id)
    close.assert_called_once_with()
    assert context.transport.created == 0


@pytest.mark.parametrize("fault", ["session", "input", "output", "project", "missing", "incomplete", "unavailable"])
def test_bad_remote_evidence_fails_without_replaying_chat(persisted_target, fault):
    context = persisted_target
    context.transport.trace_fault = fault
    with pytest.raises(TargetExecutionError):
        execution.execute_persisted_run(context.run.id)
    assert context.repository.get_run(context.run.id).status is RunStatus.FAILED
    assert context.transport.created == context.transport.deleted == 1
    assert not context.repository.list_traces(context.run.id)
    assert len(context.transport.messages) == 1


def test_missing_trace_configuration_fails_before_pod(persisted_target, monkeypatch):
    monkeypatch.delenv("AGENTGATE_INBANK_TRACE_PROJECT_ID")
    context = persisted_target
    with pytest.raises(TargetExecutionError, match="requires Trace Server"):
        execution.execute_persisted_run(context.run.id)
    assert context.transport.created == 0
