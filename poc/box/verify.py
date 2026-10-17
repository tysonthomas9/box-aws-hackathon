"""Verify saved POC evidence offline, without calling Box or creating resources."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence'


def read(name):
    return json.loads((EVIDENCE / name).read_text())


def main():
    manifest = read('source-manifest.json')
    pack_bytes = (ROOT.parent / 'company-knowledge' / 'pack.json').read_bytes()
    assert hashlib.sha256(pack_bytes).hexdigest() == manifest['pack_sha256']
    ledger = read('ledger.json')
    sources = {item['id']: item for item in manifest['items']}
    files = {item['gold_id']: item for item in ledger['files']}
    extracted = read('extraction.json')
    assert {item['gold_id'] for item in extracted} == set(sources) == {'F01', 'F02', 'P01'}
    for result in extracted:
        gold = result['gold_id']
        item = sources[gold]
        content = (item.get('text', item.get('rule')) + '\n').encode()
        assert hashlib.sha256(content).hexdigest() == files[gold]['content_sha256']
        request = read('extract-request-' + gold + '.json')
        assert request['items'] == [{'id': files[gold]['id'], 'type': 'file'}]
        assert request['fields'][0]['type'] == 'table'
        assert result['status'] == 200
        body = json.loads(result['body'])
        assert body['completion_reason'] == 'done'
        assert body['ai_agent_info']['models'] == [{'name': 'aws__claude_4_5_haiku', 'provider': 'aws'}]
        assert request['ai_agent']['basic_text']['model'] == request['ai_agent']['long_text']['model'] == 'aws__claude_4_5_haiku'
        rows = body['answer']['items']
        if 'answer' in item:
            assert len(rows) == 1 and item['answer'] in rows[0]['statement']
            assert item['subject'].split()[0] in rows[0]['subject']
        else:
            expected = ['Measure inlet pressure first',
                        'If inlet pressure is below 4 bar, restore inlet pressure and retest',
                        'Do not replace the pump if inlet pressure is below 4 bar',
                        'If pressure is at least 4 bar and E42 persists after retesting, replace the pump']
            assert [row['statement'] for row in rows] == expected
    delivery = read('delivery.json')
    assert delivery['webhook_id'] == ledger['webhook']
    assert delivery['source_id'] == files['F01']['id']
    assert delivery['capture_only'] and delivery['trigger'] == 'FILE.UPLOADED'
    assert not delivery['signature_primary_present'] and not delivery['signature_secondary_present']
    assert delivery['signature_verification'] == 'pending_keys'
    assert 0 <= delivery['seconds_after_upload_response'] <= delivery['seconds_from_upload_start']
    assert delivery['source_metadata_after_event']['parent']['id'] == ledger['folder']
    cleanup = ledger['cleanup']
    assert cleanup['webhook']['verification_status'] == 404
    assert cleanup['folder']['active_status'] == cleanup['folder']['trash_status'] == 404
    assert cleanup['files']['all_active_status'] == 404
    assert all(check['confirmed'] for check in cleanup['aws_absence_checks'])
    assert cleanup['log_group_absent'] and cleanup['completed_at']
    for path in ROOT.glob('*.py'):
        ast.parse(path.read_text())
    print('PASS: source hashes, pinned extraction, 3/3 gold items, delivery timing and cleanup evidence; Python syntax.')


if __name__ == '__main__':
    main()
