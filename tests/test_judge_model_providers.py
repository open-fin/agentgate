import json
import urllib.error
import urllib.request

import pytest

from agentgate.evaluator.judge import (
    CredentialUnavailable, JudgeModelClient, JudgeModelInvalidResponse,
    JudgeModelTimeout, JudgeModelUnavailable, JudgeRequest,
)
from agentgate.integrations.model_providers import (
    EnvCredentialResolver, FakeJudgeModel, OpenAICompatibleJudgeModel, always_fail,
    request_fingerprint, split_ref,
)

SECRET = "sk-super-secret-value"


def request(user="rate this answer", **overrides):
    return JudgeRequest(model="judge-1", user=user, **overrides)


def envelope(text="ok", finish_reason="stop", model="judge-1-2026"):
    return {
        "id": "chatcmpl-abc",
        "model": model,
        "choices": [{"message": {"content": text}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


class FakeHTTPResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def patch_urlopen(monkeypatch, handler):
    seen = []

    def fake_urlopen(http_request, timeout=None):
        seen.append((http_request, timeout))
        result = handler(len(seen))
        if isinstance(result, BaseException):
            raise result
        return FakeHTTPResponse(result)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "boom", {}, None)


# --- credential boundary -----------------------------------------------------

def test_env_resolver_reads_a_scheme_qualified_reference(monkeypatch):
    monkeypatch.setenv("JUDGE_KEY", SECRET)
    assert EnvCredentialResolver().resolve("env:JUDGE_KEY") == SECRET
    assert EnvCredentialResolver().is_available("env:JUDGE_KEY") is True


def test_unset_reference_is_unavailable_and_never_reveals_a_value(monkeypatch):
    monkeypatch.delenv("JUDGE_KEY", raising=False)
    resolver = EnvCredentialResolver()
    assert resolver.is_available("env:JUDGE_KEY") is False
    with pytest.raises(CredentialUnavailable, match="JUDGE_KEY") as caught:
        resolver.resolve("env:JUDGE_KEY")
    assert SECRET not in str(caught.value)


def test_malformed_and_unsupported_schemes_are_rejected():
    with pytest.raises(CredentialUnavailable, match="scheme:name"):
        split_ref("JUDGE_KEY")
    with pytest.raises(CredentialUnavailable, match="unsupported credential scheme"):
        split_ref("vault:JUDGE_KEY")


def test_is_available_still_raises_on_a_malformed_reference():
    # A bad scheme is a definition error, not a missing key, and must not be
    # reported as "credential not configured".
    with pytest.raises(CredentialUnavailable, match="unsupported credential scheme"):
        EnvCredentialResolver().is_available("vault:JUDGE_KEY")


# --- openai-compatible transport --------------------------------------------

def test_successful_completion_is_normalised(monkeypatch):
    patch_urlopen(monkeypatch, lambda _n: envelope("verdict"))
    client = OpenAICompatibleJudgeModel(endpoint="https://api.example/v1/chat/completions")
    response = client.complete(request())
    assert response.text == "verdict"
    assert response.resolved_model == "judge-1-2026"
    assert response.request_id == "chatcmpl-abc"
    assert (response.input_tokens, response.output_tokens) == (11, 7)
    assert response.finish_reason == "stop" and response.truncated is False
    assert response.latency_ms is not None and response.attempt_count == 1


def test_length_finish_reason_marks_the_response_truncated(monkeypatch):
    patch_urlopen(monkeypatch, lambda _n: envelope(finish_reason="length"))
    client = OpenAICompatibleJudgeModel(endpoint="https://api.example/v1")
    assert client.complete(request()).truncated is True


def test_temperature_is_always_sent_so_grading_is_not_silently_sampled(monkeypatch):
    seen = patch_urlopen(monkeypatch, lambda _n: envelope())
    client = OpenAICompatibleJudgeModel(endpoint="https://api.example/v1")
    client.complete(request(temperature=0.0, seed=7, response_format="json_object"))
    body = json.loads(seen[0][0].data)
    assert body["temperature"] == 0.0
    assert body["seed"] == 7
    assert body["response_format"] == {"type": "json_object"}


def test_timeout_maps_to_the_retryable_timeout_category(monkeypatch):
    patch_urlopen(monkeypatch, lambda _n: TimeoutError("slow"))
    client = OpenAICompatibleJudgeModel(
        endpoint="https://api.example/v1", max_attempts=2, sleep=lambda _s: None
    )
    with pytest.raises(JudgeModelTimeout) as caught:
        client.complete(request(timeout_seconds=1.0))
    # runner._error_result keys off TimeoutError to classify and mark retryable.
    assert isinstance(caught.value, TimeoutError)


def test_bad_envelope_maps_to_the_invalid_output_category(monkeypatch):
    patch_urlopen(monkeypatch, lambda _n: {"choices": []})
    client = OpenAICompatibleJudgeModel(endpoint="https://api.example/v1")
    with pytest.raises(JudgeModelInvalidResponse) as caught:
        client.complete(request())
    assert isinstance(caught.value, ValueError)


def test_non_text_content_is_an_invalid_response(monkeypatch):
    patch_urlopen(monkeypatch, lambda _n: envelope(text=None))
    client = OpenAICompatibleJudgeModel(endpoint="https://api.example/v1")
    with pytest.raises(JudgeModelInvalidResponse):
        client.complete(request())


def test_server_faults_are_retried_and_report_the_winning_attempt(monkeypatch):
    def handler(call):
        return http_error(503) if call < 3 else envelope()

    patch_urlopen(monkeypatch, handler)
    client = OpenAICompatibleJudgeModel(
        endpoint="https://api.example/v1", max_attempts=3, sleep=lambda _s: None
    )
    assert client.complete(request()).attempt_count == 3


def test_client_errors_are_not_retried(monkeypatch):
    seen = patch_urlopen(monkeypatch, lambda _n: http_error(401))
    client = OpenAICompatibleJudgeModel(
        endpoint="https://api.example/v1", max_attempts=5, sleep=lambda _s: None
    )
    with pytest.raises(JudgeModelUnavailable, match="HTTP 401"):
        client.complete(request())
    assert len(seen) == 1


def test_exhausted_retries_surface_the_last_failure(monkeypatch):
    seen = patch_urlopen(monkeypatch, lambda _n: http_error(429))
    client = OpenAICompatibleJudgeModel(
        endpoint="https://api.example/v1", max_attempts=3, sleep=lambda _s: None
    )
    with pytest.raises(JudgeModelUnavailable, match="HTTP 429"):
        client.complete(request())
    assert len(seen) == 3


def test_credential_is_sent_but_never_appears_in_repr(monkeypatch):
    monkeypatch.setenv("JUDGE_KEY", SECRET)
    seen = patch_urlopen(monkeypatch, lambda _n: envelope())
    client = OpenAICompatibleJudgeModel(
        endpoint="https://api.example/v1", credential_ref="env:JUDGE_KEY"
    )
    client.complete(request())
    headers = seen[0][0].headers
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in repr(client)
    assert "env:JUDGE_KEY" in repr(client)


def test_inline_credential_is_request_scoped_and_never_appears_in_repr(monkeypatch):
    seen = patch_urlopen(monkeypatch, lambda _n: envelope())
    client = OpenAICompatibleJudgeModel(
        endpoint="https://api.example/v1", api_key=SECRET
    )
    client.complete(request())
    assert seen[0][0].headers["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in repr(client)
    assert "credential_ref=None" in repr(client)


def test_inline_and_referenced_credentials_are_mutually_exclusive():
    with pytest.raises(ValueError, match="either credential_ref or api_key"):
        OpenAICompatibleJudgeModel(
            endpoint="https://api.example/v1",
            credential_ref="env:JUDGE_KEY",
            api_key=SECRET,
        )


def test_missing_credential_fails_at_composition_not_mid_run(monkeypatch):
    monkeypatch.delenv("JUDGE_KEY", raising=False)
    with pytest.raises(CredentialUnavailable):
        OpenAICompatibleJudgeModel(
            endpoint="https://api.example/v1", credential_ref="env:JUDGE_KEY"
        )


# --- fake model --------------------------------------------------------------

def test_fake_model_satisfies_the_client_protocol():
    assert isinstance(FakeJudgeModel(), JudgeModelClient)
    assert isinstance(
        OpenAICompatibleJudgeModel(endpoint="https://api.example/v1"), JudgeModelClient
    )


def test_fake_model_replays_a_constant_and_records_requests():
    model = FakeJudgeModel(responses="graded")
    first = model.complete(request("a"))
    second = model.complete(request("b"))
    assert (first.text, second.text) == ("graded", "graded")
    assert [item.user for item in model.requests] == ["a", "b"]
    assert model.call_count == 2 and model.last_request.user == "b"


def test_fake_model_consumes_a_script_in_order_then_reports_exhaustion():
    model = FakeJudgeModel(responses=["one", "two"])
    assert [model.complete(request()).text for _ in range(2)] == ["one", "two"]
    with pytest.raises(JudgeModelUnavailable, match="script is exhausted"):
        model.complete(request())


def test_fake_model_can_raise_a_scripted_transport_failure():
    model = always_fail(JudgeModelTimeout("too slow"))
    with pytest.raises(JudgeModelTimeout):
        model.complete(request())
    assert model.call_count == 1


def test_fake_model_can_answer_from_the_request():
    model = FakeJudgeModel(responses=lambda req: req.user.upper())
    assert model.complete(request("verdict")).text == "VERDICT"


def test_fake_request_ids_are_stable_for_identical_requests():
    model = FakeJudgeModel(responses="x")
    same = model.complete(request("a")).request_id
    assert model.complete(request("a")).request_id == same
    assert model.complete(request("b")).request_id != same


def test_fingerprint_changes_with_every_field_that_changes_a_completion():
    base = request()
    baseline = request_fingerprint(base)
    variants = [
        request(temperature=0.7), request(seed=1), request(max_output_tokens=64),
        request(response_format="json_object"), request(user="other"),
        JudgeRequest(model="judge-2", user=base.user),
        JudgeRequest(model=base.model, user=base.user, system="be strict"),
    ]
    assert all(request_fingerprint(item) != baseline for item in variants)
    assert len({request_fingerprint(item) for item in variants}) == len(variants)
