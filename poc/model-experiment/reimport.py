"""Exact POC2 re-import using the proven importer; one step per invocation."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sagemaker-bedrock'))
from base_import import aws, save, now
from import_trained import start
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'evidence/reimport.json'
NAME = 'box-hackathon-experiment-reimport-20261017'
SOURCE = 's3://box-hackathon-poc2-s17-20261017-549803795565/training/seed17/merged/'
ROLE = NAME


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status'])
    args = parser.parse_args()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if args.action == 'start':
        if state.get('import_job'):
            raise RuntimeError('Import already submitted')
        if aws('sts','get-caller-identity')['Account'] != '549803795565':
            raise RuntimeError('Wrong project')
        if not state.get('role_arn'):
            trust = {'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'bedrock.amazonaws.com'},'Action':'sts:AssumeRole','Condition':{'StringEquals':{'aws:SourceAccount':'549803795565'},'ArnLike':{'aws:SourceArn':'arn:aws:bedrock:us-east-2:549803795565:model-import-job/*'}}}]}
            result = aws('iam','create-role','--role-name',ROLE,'--assume-role-policy-document',json.dumps(trust),'--tags',json.dumps([{'Key':'project','Value':'box-hackathon'},{'Key':'poc','Value':'model-experiment'}]))
            state.update(role_arn=result['Role']['Arn'],role_name=ROLE,role_created_at=now())
            save(state,STATE)
        policy = {'Version':'2012-10-17','Statement':[{'Effect':'Allow','Action':'s3:GetObject','Resource':'arn:aws:s3:::box-hackathon-poc2-s17-20261017-549803795565/training/seed17/merged/*'},{'Effect':'Allow','Action':'s3:ListBucket','Resource':'arn:aws:s3:::box-hackathon-poc2-s17-20261017-549803795565','Condition':{'StringLike':{'s3:prefix':['training/seed17/merged','training/seed17/merged/*']}}}]}
        aws('iam','put-role-policy','--role-name',ROLE,'--policy-name','ReadExactPOC2','--policy-document',json.dumps(policy))
        state['policy']=policy
        save(state,STATE)
        start(state,SimpleNamespace(source=SOURCE,name=NAME,role_arn=state['role_arn'],poc='company-knowledge',max_imports=3))
    else:
        state['import_status']=aws('bedrock','get-model-import-job','--job-identifier',state['import_job']['jobArn'])
        state['model_arn']=state['import_status'].get('importedModelArn')
    save(state,STATE)
    print(json.dumps({k:state.get(k) for k in ['import_job','model_arn','import_status']}))


if __name__ == '__main__':
    main()
