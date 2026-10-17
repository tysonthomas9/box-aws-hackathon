"""Create only ledger-owned temporary webhook resources in us-east-2."""
import json
import tempfile
import zipfile
from pathlib import Path
from run import ROOT, LEDGER, REGION, aws, now, save


def main():
    ledger = json.loads(LEDGER.read_text())
    if ledger['aws'].get('function_name') or ledger['aws'].get('api_id'):
        raise RuntimeError('Receiver exists; inspect before creating more resources')
    owned = ledger['aws']
    name = 'box-hackathon-poc3-' + ledger['created_at'][:19].replace('-', '').replace(':', '').replace('T', '-')
    account = aws('sts', 'get-caller-identity')['Account']
    def record(key, value):
        owned[key] = value
        save('ledger.json', ledger)
    record('name', name)
    group = '/aws/lambda/' + name
    if not owned.get('role_arn'):
        aws('logs', 'create-log-group', '--log-group-name', group, '--tags', 'project=box-hackathon')
        record('log_group', group)
        aws('logs', 'put-retention-policy', '--log-group-name', group, '--retention-in-days', '1')
        trust = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow',
                 'Principal': {'Service': 'lambda.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]}
        role = aws('iam', 'create-role', '--role-name', name, '--assume-role-policy-document', json.dumps(trust),
                   '--tags', 'Key=project,Value=box-hackathon')['Role']
        record('role_name', name)
        record('role_arn', role['Arn'])
        policy = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow',
                  'Action': ['logs:CreateLogStream', 'logs:PutLogEvents'],
                  'Resource': f'arn:aws:logs:{REGION}:{account}:log-group:{group}:*'}]}
        aws('iam', 'put-role-policy', '--role-name', name, '--policy-name', 'owned-log-only',
            '--policy-document', json.dumps(policy))
        record('role_policy', 'owned-log-only')
    else:
        role = {'Arn': owned['role_arn']}
    with tempfile.TemporaryDirectory(prefix='box-poc3-', dir='/tmp') as temp:
        zip_path = Path(temp) / 'echo.zip'
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.write(ROOT / 'echo.py', 'echo.py')
        function = aws('lambda', 'create-function', '--function-name', name, '--role', role['Arn'],
                       '--runtime', 'python3.13', '--handler', 'echo.handler', '--timeout', '5',
                       '--memory-size', '128', '--zip-file', 'fileb://' + str(zip_path),
                       '--environment', json.dumps({'Variables': {'FOLDER_ID': ledger['folder'],
                        'FILE_IDS': ','.join(f['id'] for f in ledger['files'])}}),
                       '--tags', 'project=box-hackathon')
    record('function_name', name)
    record('function_arn', function['FunctionArn'])
    api = aws('apigateway', 'create-rest-api', '--name', name, '--endpoint-configuration', 'types=REGIONAL',
              '--tags', 'project=box-hackathon')
    record('api_id', api['id'])
    root = aws('apigateway', 'get-resources', '--rest-api-id', api['id'])['items'][0]['id']
    resource = aws('apigateway', 'create-resource', '--rest-api-id', api['id'], '--parent-id', root,
                   '--path-part', 'box')['id']
    aws('apigateway', 'put-method', '--rest-api-id', api['id'], '--resource-id', resource,
        '--http-method', 'POST', '--authorization-type', 'NONE', '--no-api-key-required')
    uri = f'arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions/{function["FunctionArn"]}/invocations'
    aws('apigateway', 'put-integration', '--rest-api-id', api['id'], '--resource-id', resource,
        '--http-method', 'POST', '--integration-http-method', 'POST', '--type', 'AWS_PROXY', '--uri', uri)
    aws('lambda', 'add-permission', '--function-name', name, '--statement-id', 'owned-api-only',
        '--action', 'lambda:InvokeFunction', '--principal', 'apigateway.amazonaws.com',
        '--source-arn', f'arn:aws:execute-api:{REGION}:{account}:{api["id"]}/*/POST/box',
        '--source-account', account)
    deployment = aws('apigateway', 'create-deployment', '--rest-api-id', api['id'])
    aws('apigateway', 'create-stage', '--rest-api-id', api['id'], '--stage-name', 'poc',
        '--deployment-id', deployment['id'], '--tags', 'project=box-hackathon')
    aws('apigateway', 'update-stage', '--rest-api-id', api['id'], '--stage-name', 'poc',
        '--patch-operations', json.dumps([
            {'op': 'replace', 'path': '/*/*/throttling/rateLimit', 'value': '1'},
            {'op': 'replace', 'path': '/*/*/throttling/burstLimit', 'value': '2'}]))
    record('endpoint', f'https://{api["id"]}.execute-api.{REGION}.amazonaws.com/poc/box')
    record('created_at', now())
    print('Temporary receiver created:', owned['endpoint'])


if __name__ == '__main__':
    main()
