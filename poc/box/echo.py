"""Throwaway capture-only webhook receiver; never performs downstream actions."""
import base64
import hashlib
import json
import os
from datetime import datetime, timezone


def handler(event, context):
    raw = event.get('body', '')
    body = base64.b64decode(raw) if event.get('isBase64Encoded') else raw.encode()
    if len(body) > 65536:
        return {'statusCode': 413, 'body': '{}'}
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return {'statusCode': 400, 'body': '{}'}
    headers = {key.lower(): value for key, value in event.get('headers', {}).items()}
    source = payload.get('source', {})
    target = payload.get('webhook', {}).get('target', {})
    if source.get('id') not in os.environ['FILE_IDS'].split(',') or payload.get('webhook', {}).get('id') != os.environ['WEBHOOK_ID']:
        print(json.dumps({'rejected': True, 'source_id': source.get('id'), 'webhook_id': payload.get('webhook', {}).get('id'), 'keys': list(payload)}))
        return {'statusCode': 403, 'body': '{}'}
    captured = {
        'received_at': datetime.now(timezone.utc).isoformat(),
        'event_id': payload.get('id'), 'trigger': payload.get('trigger'),
        'source_id': source.get('id'), 'webhook_id': payload.get('webhook', {}).get('id'),
        'target_id': target.get('id'), 'created_at': payload.get('created_at'),
        'delivery_id': headers.get('box-delivery-id'),
        'delivery_timestamp': headers.get('box-delivery-timestamp'),
        'signature_primary_present': bool(headers.get('box-signature-primary')),
        'signature_secondary_present': bool(headers.get('box-signature-secondary')),
        'body_sha256': hashlib.sha256(body).hexdigest(),
        'signature_verification': 'pending_keys', 'capture_only': True,
    }
    print(json.dumps(captured))
    return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'},
            'body': '{"received":true,"capture_only":true}'}
