"""Clean exact task-owned temporary resources after scoring; retain reproducible weights."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sagemaker-bedrock'))
from base_import import aws,save,now
ROOT=Path(__file__).resolve().parent
BUCKET='box-hackathon-experiment-20261017-549803795565'
GROUP='/aws/sagemaker/TrainingJobs'
KINDS=['train4','train8','eval4','eval8']


def main():
    if not (ROOT/'scores/results.json').exists():raise ValueError('Finish and seal scoring first')
    path=ROOT/'evidence/cleanup.json';ledger=json.loads(path.read_text()) if path.exists() else {'jobs':{},'deleted_objects':[]}
    states={}
    for kind in KINDS:
        state=json.loads((ROOT/f'evidence/{kind}.json').read_text())
        status=aws('sagemaker','describe-training-job','--training-job-name',state['name'])
        if status['TrainingJobStatus'] not in ['Completed','Failed','Stopped']:raise ValueError('Job is active: '+kind)
        state['status']=status;save(state,ROOT/f'evidence/{kind}.json');states[kind]=state
    logs_dir=ROOT/'evidence/logs';logs_dir.mkdir(exist_ok=True)
    for kind,state in states.items():
        entry=ledger['jobs'].setdefault(kind,{})
        if not entry.get('role_deleted_at'):
            role=aws('iam','get-role','--role-name',state['role_name'])['Role']
            if role['Arn']!=state['role_arn'] or {t['Key']:t['Value'] for t in role.get('Tags',[])}.get('poc')!='model-experiment':raise ValueError('Role ownership differs')
            aws('iam','delete-role-policy','--role-name',state['role_name'],'--policy-name','OwnedJob')
            aws('iam','delete-role','--role-name',state['role_name'])
            entry['role_deleted_at']=now();save(ledger,path)
        if not entry.get('logs_deleted_at'):
            streams=aws('logs','describe-log-streams','--log-group-name',GROUP,'--log-stream-name-prefix',state['name'])['logStreams']
            entry['log_streams_found']=len(streams)
            entry['log_streams_deleted']=[]
            for stream in streams:
                name=stream['logStreamName']
                if not name.startswith(state['name']+'/'):raise ValueError('Unexpected log prefix')
                events=aws('logs','filter-log-events','--log-group-name',GROUP,'--log-stream-names',name)
                local=logs_dir/(kind+'.json');local.write_text(json.dumps(events,indent=2)+'\n')
                entry['log_archive_sha256']=hashlib.sha256(local.read_bytes()).hexdigest()
                save(ledger,path)
                aws('logs','delete-log-stream','--log-group-name',GROUP,'--log-stream-name',name)
                entry['log_streams_deleted'].append(name)
            entry['logs_deleted_at']=now();save(ledger,path)
        script='train.py' if kind.startswith('train') else 'eval_runtime.py'
        data='train.jsonl' if kind.startswith('train') else 'evaluation.json'
        keys=[state['control_prefix']+'/'+script,state['control_prefix']+'/'+data]
        uri=state['status'].get('ModelArtifacts',{}).get('S3ModelArtifacts','')
        if uri.startswith(f's3://{BUCKET}/artifacts/{kind}/'):keys.append(uri.removeprefix(f's3://{BUCKET}/'))
        if kind.startswith('train'):
            report=json.loads((ROOT/f'evidence/{kind}-report.json').read_text())
            keys.extend(k for k in report['files'] if k.startswith(f'training/{kind}/adapter/'))
        for key in keys:
            if key in ledger['deleted_objects']:continue
            aws('s3api','delete-object','--bucket',BUCKET,'--key',key)
            ledger['deleted_objects'].append(key);save(ledger,path)
    # The shared log group is deleted only if task-created, still tagged, and empty.
    if any(s.get('created_log_group')==GROUP for s in states.values()) and not ledger.get('empty_group_checked_at'):
        streams=aws('logs','describe-log-streams','--log-group-name',GROUP)['logStreams']
        tags=aws('logs','list-tags-log-group','--log-group-name',GROUP).get('tags',{})
        if not streams and tags.get('poc')=='model-experiment':
            aws('logs','delete-log-group','--log-group-name',GROUP);ledger['empty_group_deleted_at']=now()
        else:ledger['shared_group_retained']='Other streams or ownership tags differ; no shared deletion'
        ledger['empty_group_checked_at']=now();save(ledger,path)
    models=aws('bedrock','list-imported-models')['modelSummaries']
    assert len(models)<=3
    endpoints=aws('sagemaker','list-endpoints','--name-contains','box-hackathon-experiment')['Endpoints']
    active=aws('sagemaker','list-training-jobs','--status-equals','InProgress','--name-contains','box-hackathon-experiment')['TrainingJobSummaries']
    if endpoints or active:raise ValueError('Unexpected live task resource')
    ledger.update(final_import_census=models,owned_endpoints=endpoints,owned_active_gpu_jobs=active,completed_at=now(),
        retained={'s3_bucket':BUCKET,'prefixes':['base8/','training/train4/merged/','training/train8/merged/','training/train4/report.json','training/train8/report.json','evaluation/'],
                  'purpose':'Reproducible pinned model mirrors, merged candidates, reports and raw inference evidence; no endpoints or GPU runtime'})
    save(ledger,path);print(json.dumps({'imports':len(models),'active_owned_jobs':len(active),'endpoints':len(endpoints),'temporary_roles_removed':len(ledger['jobs']),'deleted_objects':len(ledger['deleted_objects'])}))


if __name__=='__main__':main()
