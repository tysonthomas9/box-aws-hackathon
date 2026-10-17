"""Long Terraform operations must retain refreshable CLI credentials."""

import sys
from pathlib import Path

from scripts.infra import terraform


def executable(path: Path, source: str):
    path.write_text(f"#!{sys.executable}\n" + source)
    path.chmod(0o700)


def test_terraform_credentials_can_refresh_without_recursive_profile(tmp_path, monkeypatch):
    original = tmp_path / "original config with spaces"
    original.write_text("original")
    counter = tmp_path / "calls"
    aws = tmp_path / "aws"
    executable(
        aws,
        """
import json, os
from pathlib import Path
assert Path(os.environ['AWS_CONFIG_FILE']).read_text() == 'original'
p = Path(os.environ['TEST_COUNTER'])
n = int(p.read_text()) + 1 if p.exists() else 1
p.write_text(str(n))
print(json.dumps({'Version':1,'AccessKeyId':str(n),'SecretAccessKey':'fake',
                  'SessionToken':'fake','Expiration':'2030-01-01T00:00:00Z'}))
""",
    )
    runner = tmp_path / "terraform"
    executable(
        runner,
        """
import configparser, json, os, shlex, subprocess
assert 'AWS_ACCESS_KEY_ID' not in os.environ
config = configparser.RawConfigParser()
config.read(os.environ['AWS_CONFIG_FILE'])
command = shlex.split(config['profile box-hackathon']['credential_process'])
def lookup():
    return json.loads(subprocess.check_output(command))['AccessKeyId']
assert lookup() != lookup(), 'Credentials were frozen instead of fetched again'
print('refreshable')
""",
    )
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("TERRAFORM", str(runner))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(original))
    monkeypatch.setenv("AWS_PROFILE", "box-hackathon")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "stale")
    monkeypatch.setenv("TEST_COUNTER", str(counter))
    assert terraform("infra", "plan", capture=True).strip() == "refreshable"
    assert counter.read_text() == "2"
    assert original.read_text() == "original"


def test_destroy_resumes_after_outputs_and_ledger_were_removed(monkeypatch):
    from scripts import infra

    calls = []

    def run(directory, *args, capture=False):
        calls.append((directory, args))
        if directory == "infra/bootstrap" and args[:2] == ("output", "-raw"):
            return "kloop-test-123-tfstate"
        if args == ("state", "pull"):
            return '{"resources": []}'
        if args[0] == "output":
            raise AssertionError("Interrupted destroy cannot depend on deleted outputs")
        return None

    monkeypatch.setattr(infra, "terraform", run)
    monkeypatch.setattr(infra.boto3, "Session", lambda **kwargs: object())
    monkeypatch.setattr(sys, "argv", ["infra.py", "destroy"])
    monkeypatch.setenv("NAME_PREFIX", "kloop-test")
    monkeypatch.setenv("AWS_PROFILE", "box-hackathon")
    infra.main()
    assert calls[-2:] == [
        ("infra", ("destroy", "-auto-approve", "-input=false")),
        ("infra/bootstrap", ("destroy", "-auto-approve", "-input=false")),
    ]
