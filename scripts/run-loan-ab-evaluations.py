"""Run controlled local V1/V2 experiments with real execution and exact evaluator versions."""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit, urlencode
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:8097')
    parser.add_argument('--mode', choices=['base','workflow','cloudshrimp'], action='append')
    parser.add_argument('--kind', choices=['rule','llm','hybrid'], action='append')
    parser.add_argument('--smoke', action='store_true', help='one split-information case, real model calls')
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--wait-seconds', type=int, default=14400)
    parser.add_argument('--resume', type=Path, help='existing runs.json; never resubmit accepted experiments')
    args = parser.parse_args()
    origin = urlsplit(args.api)
    if origin.scheme != 'http' or origin.hostname not in ('127.0.0.1','localhost') or origin.username or origin.password or origin.path not in ('','/') or origin.query or origin.fragment:
        parser.error('Use a loopback HTTP API in external mode.')
    opener=build_opener(ProxyHandler({}))
    def call(path, payload=None):
        req=Request(args.api.rstrip('/')+path, data=None if payload is None else json.dumps(payload).encode(),
                    headers={'Content-Type':'application/json','Authorization':'Bearer local'})
        with opener.open(req,timeout=45) as response:
            value=json.load(response)
            if isinstance(value,dict) and 'code' in value and 'data' in value:
                if str(value['code'])!='0':raise RuntimeError(value.get('message','API rejected'))
                value=value['data']
            return value
    if args.resume:
        output=args.resume.resolve().parent; runs=json.loads(args.resume.read_text())
    else:
        targets=call('/api/bank-targets')
        catalog={e['id']:e for e in call('/api/evaluators')}
        records=json.loads((ROOT/'src/agentgate/demo/loan-core-evaluators.json').read_text())
        ids={r['key']:r['id'] for r in records}
        plans=[]
        for mode in args.mode or ['base','workflow','cloudshrimp']:
            chosen={t['descriptor']['ref']['external_version_id']:t['descriptor'] for t in targets if t['descriptor']['ref']['external_target_id']=='loan-'+mode}
            if not {'evolution-v1','evolution-v2'} <= chosen.keys():raise RuntimeError('Missing evolution versions for '+mode)
            ds=call('/api/datasets/loan-ab-'+mode+'/versions/1')
            rules=['final-state','required-tool','forbidden-tool','tool-arguments',ids['path']]
            if mode=='cloudshrimp':rules.append('skill-routing')
            for kind in args.kind or ['rule','llm','hybrid']:
                selected=rules if kind=='rule' else [ids[mode+'-'+kind]]
                refs=[]
                for identity in selected:
                    row=catalog.get(identity)
                    if not row or not row['enabled'] or not row['latest_version']:raise RuntimeError('Evaluator not ready: '+identity)
                    refs.append({'evaluator_id':identity,'evaluator_version':row['latest_version']})
                label={'base':'基础编排','workflow':'工作流','cloudshrimp':'云虾'}[mode]
                kind_label={'rule':'规则','llm':'LLM','hybrid':'规则+LLM'}[kind]
                scope='冒烟1例' if args.smoke else '完整20例'
                plans.append(dict(name=f'贷款演进 A/B · {label} · {kind_label} · {scope}',mode=mode,
                    baseline_version='evolution-v1',candidate_version='evolution-v2',
                    baseline_descriptor_sha256=chosen['evolution-v1']['content_sha256'],
                    candidate_descriptor_sha256=chosen['evolution-v2']['content_sha256'],
                    dataset_id='loan-ab-'+mode,dataset_version=1,evaluator_refs=refs,timeout_seconds=300,
                    **({'case_ids':[ds['cases'][12]['id']]} if args.smoke else {})))
        if args.plan_only:
            print(json.dumps(plans,ensure_ascii=False,indent=2));return
        output=ROOT/'runtime/loan-ab-acceptance'/time.strftime('%Y%m%d-%H%M%S'); output.mkdir(parents=True,exist_ok=False)
        (output/'plans.json').write_text(json.dumps(plans,ensure_ascii=False,indent=2))
        runs=[]
        for plan in plans:
            # Unknown POST outcomes are never retried automatically.
            pair=call('/api/bank-comparisons',plan)
            runs.append({'mode':plan['mode'],'name':plan['name'],**pair})
            (output/'runs.json').write_text(json.dumps(runs,ensure_ascii=False,indent=2))
            print('Created '+plan['name'],flush=True)
    pending={r[side]['run_id'] for r in runs for side in ('baseline','candidate')}
    deadline=time.monotonic()+args.wait_seconds
    while pending and time.monotonic()<deadline:
        for identity in tuple(pending):
            state=call('/api/runs/'+identity+'/status')['status']
            if state in ('completed','failed','cancelled'):
                report=call('/api/runs/'+identity+'/samples')
                (output/(identity+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
                pending.remove(identity);print(identity+': '+state,flush=True)
        if pending:time.sleep(5)
    if pending:raise SystemExit('Runs continue; resume with --resume '+str(output/'runs.json'))
    for pair in runs:
        query=urlencode({'baseline_run_id':pair['baseline']['run_id'],'candidate_run_id':pair['candidate']['run_id']})
        comparison=call('/api/run-comparisons?'+query)
        (output/(pair['baseline']['run_id']+'-comparison.json')).write_text(json.dumps(comparison,ensure_ascii=False,indent=2))
        print(pair['name']+': overall delta='+str(comparison['overall_score_delta']))
    print('Evidence: '+str(output))


if __name__=='__main__':main()
