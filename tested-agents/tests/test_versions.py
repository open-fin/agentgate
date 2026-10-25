"""Behavioral contracts for isolated evolution releases (scripted model, not live acceptance)."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from bank_agents.app import create_app
from bank_agents.runtime import Runtime
from bank_agents.store import Store
from bank_agents.versions import session_scope, loan_version
from test_runtime import ScriptedModel


class ContextModel(ScriptedModel):
    def structured(self, prompt, messages, evidence):
        text = ' '.join(m.get('content') or '' for m in messages if m['role'] == 'user')
        if '路由器' in prompt:
            return {'skill': 'application_status' if '查询' in messages[-1]['content'] else 'loan_application'}
        return {'amount': 80000 if '8万' in text else None,
                'purpose': '购买农机' if '农机' in text else None,
                'intent': 'status' if '查询' in messages[-1]['content'] else 'apply'}

    def complete(self, messages, evidence, tools=None, **kwargs):
        text = ' '.join(m.get('content') or '' for m in messages if m['role'] == 'user')
        if tools and ('8万' not in text or '农机' not in text):
            return {'role': 'assistant', 'content': '测试申请还缺资料，请补充。'}
        return super().complete(messages, evidence, tools=tools)


@pytest.mark.parametrize('mode', ['base', 'workflow', 'cloudshrimp'])
def test_split_information_recovers_only_in_v2(tmp_path, mode):
    runtime = Runtime(Store(tmp_path/'bank.db'), ContextModel(), tmp_path/'traces')
    statuses = {}
    for version in ('evolution-v1', 'evolution-v2'):
        sid = runtime.store.create_session(session_scope(mode, version), 'test-low')
        for text in ('我想申请8万元贷款。', '用途是购买农机。'):
            result = runtime.execute(mode, sid, str(uuid4()), text, version)
        assert result['agent_version'] == version
        statuses[version] = result['final_state']['status']
    assert statuses == {'evolution-v1': 'no_application', 'evolution-v2': 'approved'}


def test_session_and_http_versions_cannot_be_switched(tmp_path):
    runtime = Runtime(Store(tmp_path/'bank.db'), ScriptedModel(), tmp_path/'traces')
    client = TestClient(create_app(runtime))
    sid = str(uuid4())
    envelope = {'requestId': sid, 'timestamp': 1, 'data': {}}
    assert client.post('/agent-api/loan-base-evolution-v1/chatabc/init_session', json=envelope).status_code == 200
    envelope['data'] = {'session_id': sid, 'txt': '申请8万元购买农机', 'stream': True}
    assert client.post('/agent-api/loan-base-evolution-v2/chatabc/chat', json=envelope).status_code == 422
    with pytest.raises(ValueError):
        runtime.execute('base', sid, str(uuid4()), '申请', 'unknown')
    records = client.get('/agents').json()
    assert len({(r['agent_id'], r['agent_version']) for r in records}) == 9


def test_skill_permission_blocks_before_business_write(tmp_path):
    from bank_agents.telemetry import Evidence
    from bank_agents.tools import LoanTools
    runtime = Runtime(Store(tmp_path/'bank.db'), ScriptedModel(), tmp_path/'traces')
    sid = runtime.store.create_session('cloudshrimp', 'test-low')
    rid = str(uuid4()); runtime.store.reserve(rid, sid, {})
    evidence = Evidence(tmp_path/'traces', str(uuid4()), sid, 'cloudshrimp', 'query')
    tools = LoanTools(runtime.store, sid, rid, evidence, allowed_tools=frozenset({'get_application'}))
    assert tools.invoke('submit_application', {'amount': 80000, 'purpose': '购买农机'})['error'] == 'TOOL_REJECTED'
    assert runtime.store.application(sid)['status'] == 'no_application'
    evidence.finish({'output': 'test'})


def test_legacy_request_idempotency_is_preserved(tmp_path):
    runtime = Runtime(Store(tmp_path/'bank.db'), ScriptedModel(), tmp_path/'traces')
    sid = runtime.store.create_session('base', 'test-low')
    rid = str(uuid4())
    runtime.store.reserve(rid, sid, {'text':'old request','mode':'base'})
    runtime.store.finish(rid, {'output':'previous result'})
    assert runtime.execute('base', sid, rid, 'old request') == {'output':'previous result'}
