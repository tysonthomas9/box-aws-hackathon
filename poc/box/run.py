"""Isolated POC 3 operations. Credentials are read at runtime and never saved."""
import argparse
import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence'
LEDGER = EVIDENCE / 'ledger.json'
PROFILE = 'box-hackathon'
REGION = 'us-east-2'
SECRET = 'box-hackathon/box-ccg'
MODEL = 'aws__claude_4_5_haiku'


def now():
    return datetime.now(timezone.utc).isoformat()


def aws(*args):
    output = subprocess.check_output(
        ['aws', *args, '--profile', PROFILE, '--region', REGION, '--output', 'json'],
        text=True)
    return json.loads(output) if output.strip() else {}


def save(name, value):
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(value, indent=2) + '\n')


class Box:
    def __init__(self):
        self.secret = json.loads(aws('secretsmanager', 'get-secret-value',
                                    '--secret-id', SECRET)['SecretString'])
        self.token = self.secret['developer_token']
        self.calls = json.loads((EVIDENCE / 'calls.json').read_text()) if (EVIDENCE / 'calls.json').exists() else []

    def request(self, method, path, data=None, multipart=None):
        headers = {'Authorization': 'Bearer ' + self.token,
                   'Accept': 'application/json'}
        url = 'https://api.box.com/2.0' + path
        if multipart:
            url = 'https://upload.box.com/api/2.0' + path
            data, content_type = multipart
            headers['Content-Type'] = content_type
        elif data is not None:
            data = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        start = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    url, data=data, headers=headers, method=method), timeout=180) as r:
                status, body, request_id = r.status, r.read().decode(), r.headers.get('box-request-id')
        except urllib.error.HTTPError as e:
            status, body, request_id = e.code, e.read().decode(), e.headers.get('box-request-id')
        for key in ('developer_token', 'client_secret'):
            if self.secret.get(key):
                body = body.replace(self.secret[key], '[REDACTED]')
        result = {'at': now(), 'method': method, 'path': path, 'status': status,
                  'seconds': round(time.monotonic() - start, 4),
                  'request_id': request_id, 'body': body}
        self.calls.append({k: v for k, v in result.items() if k != 'body'})
        save('calls.json', self.calls)
        if status == 401:
            save('token-expired.json', result)
            raise RuntimeError('Box token expired or invalid; stopped without requesting another')
        return result


def decoded(result, expected):
    if result['status'] != expected:
        save('last-error.json', result)
        raise RuntimeError('Box returned status ' + str(result['status']) + '; see last-error.json')
    return json.loads(result['body']) if result['body'] else None


def multipart(name, folder, content):
    boundary = 'poc3-' + uuid.uuid4().hex
    attributes = json.dumps({'name': name, **({'parent': {'id': folder}} if folder else {})})
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="attributes"\r\n\r\n'
            f'{attributes}\r\n--{boundary}\r\nContent-Disposition: form-data; '
            f'name="file"; filename="{name}"\r\nContent-Type: text/plain\r\n\r\n').encode()
    return body + content + f'\r\n--{boundary}--\r\n'.encode(), 'multipart/form-data; boundary=' + boundary


def documents():
    if LEDGER.exists():
        raise RuntimeError('Existing ledger: inspect before creating another folder')
    box = Box()
    me_result = box.request('GET', '/users/me?fields=id,name')
    me = decoded(me_result, 200)
    save('identity.json', {'at': now(), 'status': 200, 'id': me['id'], 'name': me['name'],
                           'auth': 'developer_token', 'ccg': 'still requires admin authorization'})
    print('Developer token verified for:', me['name'], flush=True)
    folder = decoded(box.request('POST', '/folders', {
        'name': 'Halvard POC3 ' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'),
        'parent': {'id': '0'}}), 201)
    ledger = {'created_at': now(), 'actor_id': me['id'], 'folder': folder['id'],
              'folder_name': folder['name'], 'files': [], 'aws': {}, 'cleanup': {}}
    save('ledger.json', ledger)
    check = decoded(box.request('GET', '/folders/' + folder['id'] + '?fields=id,name,shared_link,has_collaborations'), 200)
    save('folder-check.json', check)
    pack_bytes = (ROOT.parent / 'company-knowledge' / 'pack.json').read_bytes()
    pack = json.loads(pack_bytes)
    selected = [pack['facts'][0], pack['facts'][1], pack['procedures'][0]]
    manifest = {'pack_sha256': hashlib.sha256(pack_bytes).hexdigest(), 'items': selected}
    save('source-manifest.json', manifest)
    for item in selected:
        content = (item.get('text', item.get('rule')) + '\n').encode()
        result = box.request('POST', '/files/content', multipart=multipart(item['source'], folder['id'], content))
        f = decoded(result, 201)['entries'][0]
        ledger['files'].append({'id': f['id'], 'name': f['name'], 'gold_id': item['id'],
                                'sha1': hashlib.sha1(content).hexdigest(), 'content_sha256': hashlib.sha256(content).hexdigest()})
        save('ledger.json', ledger)
        actual = decoded(box.request('GET', '/files/' + f['id'] + '?fields=id,name,parent,sha1'), 200)
        assert actual['parent']['id'] == folder['id'] and actual['sha1'] == hashlib.sha1(content).hexdigest()
        print('Uploaded and verified:', f['name'], f['id'], flush=True)
    extract(box, ledger)
    print('Document stage complete. Folder:', folder['id'], flush=True)


def extract(box, ledger):
    results = []
    for f in ledger['files']:
        payload = {
            'items': [{'id': f['id'], 'type': 'file'}],
            'fields': [{'key': 'items', 'type': 'table', 'displayName': 'Facts and procedures',
                        'prompt': 'Extract every fact or procedure as one row. Preserve exact names, values, units, thresholds, conditions, action order and prohibitions. Do not infer facts.',
                        'fields': [{'key': 'subject', 'type': 'string', 'displayName': 'Subject'},
                                   {'key': 'statement', 'type': 'string', 'displayName': 'Complete fact or procedure'}]}],
            'ai_agent': {'type': 'ai_agent_extract_structured',
                         'basic_text': {'model': MODEL}, 'long_text': {'model': MODEL}}}
        save('extract-request-' + f['gold_id'] + '.json', payload)
        result = box.request('POST', '/ai/extract_structured', payload)
        result.update(gold_id=f['gold_id'], file_id=f['id'], requested_model=MODEL)
        results.append(result)
        save('extraction.json', results)
        print('Extraction:', f['name'], result['status'], flush=True)
        if result['status'] in (402, 403):
            print('Box AI entitlement/permission denial; skipping remaining AI calls per official skill.', flush=True)
            break
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['documents', 'extract'])
    args = parser.parse_args()
    if args.stage == 'documents':
        documents()
    elif args.stage == 'extract':
        extract(Box(), json.loads(LEDGER.read_text()))


if __name__ == '__main__':
    main()
