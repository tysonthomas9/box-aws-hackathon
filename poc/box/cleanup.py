"""Delete only the exact POC-owned resources recorded in the ledger."""
import json
import subprocess
from run import LEDGER, PROFILE, REGION, Box, aws, decoded, now, save


def main():
    ledger = json.loads(LEDGER.read_text())
    box = Box()
    def record(key, value):
        ledger['cleanup'][key] = value
        save('ledger.json', ledger)
    # Inspect only the owned folder, and refuse if anything unowned appeared.
    items = decoded(box.request('GET', '/folders/' + ledger['folder'] + '/items?fields=id,name,type&limit=100'), 200)
    expected = {f['id'] for f in ledger['files']}
    assert items['total_count'] == len(expected)
    assert {f['id'] for f in items['entries']} == expected
    if ledger.get('webhook'):
        decoded(box.request('DELETE', '/webhooks/' + ledger['webhook']), 204)
        result = box.request('GET', '/webhooks/' + ledger['webhook'])
        assert result['status'] == 404
        record('webhook', {'deleted_at': now(), 'verification_status': 404})
    decoded(box.request('DELETE', '/folders/' + ledger['folder'] + '?recursive=true'), 204)
    record('folder_trashed', now())
    # Permanently purge only the newly created folder and its verified owned files.
    purge = box.request('DELETE', '/folders/' + ledger['folder'] + '/trash')
    save('folder-purge.json', purge)
    decoded(purge, 204)
    active = box.request('GET', '/folders/' + ledger['folder'] + '?fields=id')
    trash = box.request('GET', '/folders/' + ledger['folder'] + '/trash?fields=id')
    assert active['status'] == trash['status'] == 404
    record('folder', {'purged_at': now(), 'active_status': 404, 'trash_status': 404})
    for f in ledger['files']:
        result = box.request('GET', '/files/' + f['id'] + '?fields=id')
        assert result['status'] == 404
    record('files', {'verified_at': now(), 'all_active_status': 404})
    owned = ledger['aws']
    if owned.get('api_id'):
        aws('apigateway', 'delete-rest-api', '--rest-api-id', owned['api_id'])
        record('api', now())
    if owned.get('function_name'):
        aws('lambda', 'delete-function', '--function-name', owned['function_name'])
        record('function', now())
    if owned.get('role_policy'):
        aws('iam', 'delete-role-policy', '--role-name', owned['role_name'], '--policy-name', owned['role_policy'])
        record('role_policy', now())
    if owned.get('role_name'):
        aws('iam', 'delete-role', '--role-name', owned['role_name'])
        record('role', now())
    if owned.get('log_group'):
        aws('logs', 'delete-log-group', '--log-group-name', owned['log_group'])
        record('log_group', now())
    checks = [
        (['apigateway', 'get-rest-api', '--rest-api-id', owned['api_id']], 'NotFoundException'),
        (['lambda', 'get-function', '--function-name', owned['function_name']], 'ResourceNotFoundException'),
        (['iam', 'get-role', '--role-name', owned['role_name']], 'NoSuchEntity'),
    ]
    verification = []
    for command, expected_error in checks:
        result = subprocess.run(['aws', *command, '--profile', PROFILE, '--region', REGION, '--output', 'json'],
                                capture_output=True, text=True)
        assert result.returncode and expected_error in result.stderr
        verification.append({'command': command, 'expected_error': expected_error, 'confirmed': True})
    groups = aws('logs', 'describe-log-groups', '--log-group-name-prefix', owned['log_group'])['logGroups']
    assert not any(g['logGroupName'] == owned['log_group'] for g in groups)
    record('aws_absence_checks', verification)
    record('log_group_absent', True)
    record('completed_at', now())
    print('Cleanup verified: owned webhook, folder/files, API, Lambda, role/policy and log group removed.')


if __name__ == '__main__':
    main()
