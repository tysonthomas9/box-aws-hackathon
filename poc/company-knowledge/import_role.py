"""Create only the tagged POC2 role scoped to its merged-model prefix."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sagemaker-bedrock'))
from base_import import aws, save

NAME = 'box-hackathon-poc2-s17-import-20261017'
BUCKET = 'box-hackathon-poc2-s17-20261017-549803795565'
PREFIX = 'training/seed17/merged/'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    tags = [{'Key':'project','Value':'box-hackathon'}, {'Key':'poc','Value':'company-knowledge'}]
    if aws('sts','get-caller-identity')['Account'] != '549803795565':
        raise RuntimeError('Wrong project')
    if not state.get('role_arn'):
        trust = {'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'bedrock.amazonaws.com'},
            'Action':'sts:AssumeRole','Condition':{'StringEquals':{'aws:SourceAccount':'549803795565'},
            'ArnLike':{'aws:SourceArn':'arn:aws:bedrock:us-east-2:549803795565:model-import-job/*'}}}]}
        role = aws('iam','create-role','--role-name',NAME,'--assume-role-policy-document',json.dumps(trust),'--tags',json.dumps(tags))
        state.update(role_arn=role['Role']['Arn'], role_name=NAME, trust=trust)
        save(state,args.state)
    policy = {'Version':'2012-10-17','Statement':[
        {'Effect':'Allow','Action':'s3:GetObject','Resource':f'arn:aws:s3:::{BUCKET}/{PREFIX}*'},
        {'Effect':'Allow','Action':'s3:ListBucket','Resource':f'arn:aws:s3:::{BUCKET}',
         'Condition':{'StringLike':{'s3:prefix':[PREFIX.rstrip('/'),PREFIX+'*']}}}]}
    aws('iam','put-role-policy','--role-name',NAME,'--policy-name','ReadOwnedMerged','--policy-document',json.dumps(policy))
    state['policy']=policy
    save(state,args.state)
    print(state['role_arn'])


if __name__ == '__main__':
    main()
