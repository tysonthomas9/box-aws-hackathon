"""Register a webhook on the owned folder and upload one new owned file version."""
import json
from run import ROOT, LEDGER, Box, decoded, multipart, now, save, aws


def main():
    ledger = json.loads(LEDGER.read_text())
    box = Box()
    if not ledger.get('webhook'):
        response = box.request('POST', '/webhooks', {
            'target': {'id': ledger['folder'], 'type': 'folder'},
            'address': ledger['aws']['endpoint'], 'triggers': ['FILE.UPLOADED']})
        save('webhook-create.json', response)
        webhook = decoded(response, 201)
        ledger['webhook'] = webhook['id']
        save('ledger.json', ledger)
    else:
        webhook = {'id': ledger['webhook']}
    actual = decoded(box.request('GET', '/webhooks/' + webhook['id']), 200)
    assert actual['target']['id'] == ledger['folder']
    save('webhook-check.json', actual)
    aws('lambda', 'update-function-configuration', '--function-name', ledger['aws']['function_name'],
        '--environment', json.dumps({'Variables': {'FOLDER_ID': ledger['folder'],
        'FILE_IDS': ','.join(f['id'] for f in ledger['files']), 'WEBHOOK_ID': ledger['webhook']}}))
    f = ledger['files'][0]
    actual = decoded(box.request('GET', '/files/' + f['id'] + '?fields=id,name,parent,sha1,file_version'), 200)
    assert actual['parent']['id'] == ledger['folder']
    pack = json.loads((ROOT.parent / 'company-knowledge' / 'pack.json').read_text())
    content = (pack['facts'][0]['text'] + '\nPOC 3 webhook delivery edit ' + now() + '.\n').encode()
    start = now()
    response = box.request('POST', '/files/' + f['id'] + '/content',
                           multipart=multipart(f['name'], None, content))
    result = decoded(response, 201)['entries'][0]
    save('file-edit.json', {'started_at': start, 'completed_at': now(),
                           'file_id': f['id'], 'previous_version': actual['file_version'],
                           'new_version': result['file_version'], 'upload': response})
    check = decoded(box.request('GET', '/files/' + f['id'] + '?fields=id,name,parent,sha1,file_version'), 200)
    assert check['file_version']['id'] == result['file_version']['id']
    save('file-edit-check.json', check)
    print('Webhook registered:', webhook['id'], '; file version edited:', f['id'])


if __name__ == '__main__':
    main()
