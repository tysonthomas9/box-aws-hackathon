"""Check Box CCG authorization without persisting credentials or access tokens."""
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROFILE = 'box-hackathon'
REGION = 'us-east-2'
SECRET_ID = 'box-hackathon/box-ccg'


def aws(*args):
    return json.loads(subprocess.check_output(
        ['aws', *args, '--profile', PROFILE, '--region', REGION, '--output', 'json'],
        text=True,
    ))


def main():
    plan = aws('freetier', 'get-account-plan-state')
    secret = json.loads(aws('secretsmanager', 'get-secret-value',
                            '--secret-id', SECRET_ID)['SecretString'])
    fields = ['client_id', 'client_secret', 'box_subject_type', 'box_subject_id']
    if not all(secret.get(key) for key in fields):
        raise ValueError('CCG secret is missing a required field')
    if secret['box_subject_type'] != 'user':
        raise ValueError('This POC requires the authorized user subject')
    request = urllib.request.Request(
        'https://api.box.com/oauth2/token', method='POST',
        data=urllib.parse.urlencode({
            **{key: secret[key] for key in fields},
            'grant_type': 'client_credentials',
        }).encode(),
    )
    evidence = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'profile': PROFILE, 'region': REGION, 'secret_id': SECRET_ID,
        'plan_type': plan['accountPlanType'],
        'plan_status': plan['accountPlanStatus'],
        'subject_type': 'user',
        'webhook_key_fields_present': any(
            'webhook' in key.lower() or 'primary' in key.lower()
            or 'secondary' in key.lower() for key in secret
        ),
        'resources_created': [],
    }
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            token_response = json.load(response)
            evidence.update(status=response.status,
                            token_received=bool(token_response.get('access_token')))
    except urllib.error.HTTPError as error:
        body = error.read().decode()
        # Error bodies must never expose a credential if an upstream echoes input.
        for key in fields:
            if key != 'box_subject_type':
                body = body.replace(str(secret[key]), '[REDACTED]')
        evidence.update(status=error.code, error_body=body)
    path = Path(__file__).parent / 'evidence' / 'preflight.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2))
    return 0 if evidence.get('token_received') else 2


if __name__ == '__main__':
    raise SystemExit(main())
