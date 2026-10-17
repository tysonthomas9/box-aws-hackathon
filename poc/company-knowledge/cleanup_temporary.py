"""Remove only tagged POC2 temporary roles, control files and empty logs; KEEP import/weights."""
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sagemaker-bedrock'))
from base_import import aws


def main():
    evidence = Path(__file__).resolve().parent / 'evidence/temporary-cleanup.json'
    result = json.loads(evidence.read_text()) if evidence.exists() else {'deleted': []}
    tags = {'project': 'box-hackathon', 'poc': 'company-knowledge'}
    def done(label):
        result['deleted'].append({'resource':label,'at':datetime.now(timezone.utc).isoformat()})
        evidence.write_text(json.dumps(result,indent=2)+'\n')
    def deleted(label):
        return any(r['resource']==label for r in result['deleted'])
    roles = [('box-hackathon-poc2-s17-20261017','OwnedTraining'),
             ('box-hackathon-poc2-s17-import-20261017','ReadOwnedMerged'),
             ('box-hackathon-poc2-eval17-20261017','OwnedTraining')]
    for role, policy in roles:
        if deleted(role): continue
        actual = {t['Key']:t['Value'] for t in aws('iam','list-role-tags','--role-name',role)['Tags']}
        if any(actual.get(k)!=v for k,v in tags.items()): raise RuntimeError('Role ownership differs')
        if not deleted(role+'/'+policy):
            aws('iam','delete-role-policy','--role-name',role,'--policy-name',policy)
            done(role+'/'+policy)
        aws('iam','delete-role','--role-name',role)
        done(role)
    bucket = 'box-hackathon-poc2-s17-20261017-549803795565'
    actual = {t['Key']:t['Value'] for t in aws('s3api','get-bucket-tagging','--bucket',bucket)['TagSet']}
    if any(actual.get(k)!=v for k,v in tags.items()): raise RuntimeError('Bucket ownership differs')
    keys = ['control/train.py','control/train.jsonl','control/evaluation/eval_runtime.py','control/evaluation/prompts.json']
    for key in keys:
        label='s3://'+bucket+'/'+key
        if not deleted(label):
            aws('s3api','delete-object','--bucket',bucket,'--key',key)
            done(label)
    group='/aws/sagemaker/TrainingJobs'
    if not deleted(group):
        arn='arn:aws:logs:us-east-2:549803795565:log-group:'+group
        actual=aws('logs','list-tags-for-resource','--resource-arn',arn)['tags']
        if any(actual.get(k)!=v for k,v in tags.items()): raise RuntimeError('Log-group ownership differs')
        streams=aws('logs','describe-log-streams','--log-group-name',group)['logStreams']
        if not streams:
            aws('logs','delete-log-group','--log-group-name',group)
            done(group)
        else:
            result['log_group_retained_reason']='Streams remain; no stream deleted automatically'
    result.update(retained_import='arn:aws:bedrock:us-east-2:549803795565:imported-model/x2feesmws1lw',
        retained_bucket=bucket, retained_prefixes=['base/','training/seed17/','evaluation/seed17/'],
        reason='Coordinator explicitly retains candidate and source/evidence pending demo decision')
    evidence.write_text(json.dumps(result,indent=2)+'\n')


if __name__ == '__main__':
    main()
