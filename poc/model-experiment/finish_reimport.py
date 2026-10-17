"""Seal re-import outcome; delete only coordinator-approved duplicate and owned role."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sagemaker-bedrock'))
from base_import import aws,save,now
ROOT=Path(__file__).resolve().parent
OLD='arn:aws:bedrock:us-east-2:549803795565:imported-model/x2feesmws1lw'


def main():
    state=json.loads((ROOT/'evidence/reimport.json').read_text());cold=json.loads((ROOT/'evidence/cold-runtime.json').read_text())
    if cold.get('outcome') not in ['served','never_served_within_10min']:raise ValueError('Bounded cold test must finish first')
    path=ROOT/'evidence/reimport-outcome.json';ledger=json.loads(path.read_text()) if path.exists() else {}
    if not ledger.get('old_deleted_at'):
        old=aws('bedrock','get-imported-model','--model-identifier',OLD)
        if old['modelDataSource']!=state['import_status']['modelDataSource']:raise ValueError('Old/new sources differ')
        ledger.update(old_model=old,new_model=state['model_arn'],outcome=cold['outcome'],cold_start_seconds=cold['observed_elapsed_seconds'],cold_attempts=len(cold['attempts']),authorization='Coordinator2026-10-17T07:17:43Z: delete old exact duplicate after bounded test regardless of outcome')
        save(ledger,path)
        aws('bedrock','delete-imported-model','--model-identifier',OLD)
        ledger['old_deleted_at']=now();save(ledger,path)
    if not ledger.get('import_role_deleted_at'):
        role=aws('iam','get-role','--role-name',state['role_name'])['Role']
        tags={t['Key']:t['Value'] for t in role.get('Tags',[])}
        if tags.get('poc')!='model-experiment' or role['Arn']!=state['role_arn']:raise ValueError('Role ownership mismatch')
        aws('iam','delete-role-policy','--role-name',state['role_name'],'--policy-name','ReadExactPOC2')
        aws('iam','delete-role','--role-name',state['role_name'])
        ledger['import_role_deleted_at']=now();save(ledger,path)
    census=aws('bedrock','list-imported-models')['modelSummaries']
    if len(census)>3 or any(m['modelArn']==OLD for m in census):raise ValueError('Import census differs from cleanup')
    ledger.update(census_after=census,checked_at=now(),conclusion='one-off failure' if cold['outcome']=='served' else 'weights or import path suspect; no more imports')
    save(ledger,path)
    print(json.dumps({'conclusion':ledger['conclusion'],'cold_start_seconds':ledger['cold_start_seconds'],'attempts':ledger['cold_attempts'],'imports':len(census),'old_deleted_at':ledger['old_deleted_at'],'role_deleted_at':ledger['import_role_deleted_at']}))


if __name__=='__main__':main()
