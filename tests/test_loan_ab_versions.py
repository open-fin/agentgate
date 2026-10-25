"""Version-aware local A/B API and immutable portable acceptance inputs."""
import json
from importlib.resources import files
from fastapi.testclient import TestClient
from agentgate.server.app import create_app
from agentgate.domain import Case
from agentgate.integrations.targets.local_bank import local_bank_target
from test_local_bank_adapter import Client


class Releases(Client):
    def call(self, path, payload=None, **kwargs):
        rows = super().call(path, payload, **kwargs)
        if path == '/agents':
            return [{**rows[0], 'agent_version': v, 'agent_name': 'loan-base-'+v,
                     'prompt': 'release '+v} for v in ('v1', 'evolution-v1', 'evolution-v2')]
        return rows


class Dispatcher:
    def __init__(self): self.runs = []
    def submit(self, run_id): self.runs.append(run_id)
    def cancel(self, run_id): pass


def test_portable_ab_cases_are_valid_and_originals_are_not_replaced():
    records = json.loads(files('agentgate.demo').joinpath('loan-ab-datasets.json').read_text())
    assert len(records) == 3
    for record in records:
        assert len(record['cases']) == 20
        cases = [Case.model_validate(c) for c in record['cases']]
        assert len({c.id for c in cases}) == 20
        assert all(c.turns and all(t.expectations for t in c.turns) for c in cases)
        assert record['id'].startswith('loan-ab-')


def test_ab_local_only_pins_versions_and_rejects_stale_selection(tmp_path, monkeypatch):
    from agentgate.server.routes import bank_targets
    monkeypatch.setattr(bank_targets, 'LocalBankClient', Releases)
    dispatcher = Dispatcher()
    app = create_app(tmp_path/'ab.db', dispatcher=dispatcher)
    with TestClient(app) as http:
        payload = dict(name='版本演进', mode='base', baseline_version='evolution-v1',
            candidate_version='evolution-v2', dataset_id='loan-ab-base', dataset_version=1,
            case_ids=['base-ab-core-1'], evaluator_refs=[{'evaluator_id':'final-state','evaluator_version':'1'}])
        for side, version in [('baseline','evolution-v1'),('candidate','evolution-v2')]:
            payload[side+'_descriptor_sha256'] = local_bank_target(Releases(), 'base', version)[0].content_sha256
        assert http.post('/api/bank-comparisons',json=payload).status_code == 403
        assert http.post('/api/bank-comparisons',headers={'Authorization':'Bearer real-bank-token'},json=payload).status_code == 403
        headers={'Authorization':'Bearer local'}
        assert http.post('/api/bank-comparisons',headers=headers,json={**payload,'candidate_descriptor_sha256':'0'*64}).status_code == 422
        assert http.post('/api/bank-comparisons',headers=headers,json={**payload,'candidate_version':'unknown'}).status_code == 422
        assert not dispatcher.runs
        response=http.post('/api/bank-comparisons',headers=headers,json=payload)
        assert response.status_code==202,response.text
        data=response.json()['data']; repo=app.state.dependencies.repository
        a,b=[repo.get_run(data[side]['run_id']) for side in ('baseline','candidate')]
        assert a.manifest.target.ref.external_version_id=='evolution-v1'
        assert b.manifest.target.ref.external_version_id=='evolution-v2'
        assert a.manifest.dataset==b.manifest.dataset
        assert a.manifest.evaluator_specs==b.manifest.evaluator_specs
        assert a.manifest.selected_case_ids==b.manifest.selected_case_ids==('base-ab-core-1',)
        assert repo.get_evaluation_task(a.id).name=='版本演进'
        assert len(dispatcher.runs)==2


def test_adapter_rejects_evidence_from_another_release():
    import pytest
    from agentgate.domain import CaseTurn
    from agentgate.integrations.targets.local_bank import LocalBankAdapter
    from agentgate.run.target_protocol import CaseExecutionRequest, TargetExecutionError
    client = Releases()
    _, target = local_bank_target(client, 'base', 'evolution-v2')
    case = Case(id='case', name='Version evidence', turns=(CaseTurn(input={'txt':'loan'}),))
    request = CaseExecutionRequest('exec','run',case,target,30,'00-'+'a'*32+'-'+'b'*16+'-01')
    # The test peer advertises V2 but emits legacy V1 evidence: it must not be accepted.
    with pytest.raises(TargetExecutionError, match='correlation mismatch'):
        LocalBankAdapter(client,client.trace_server).start(request)
