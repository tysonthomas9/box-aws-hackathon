"""Long Terraform operations must retain refreshable CLI credentials."""

import os
import sys
from pathlib import Path

import pytest

from scripts.infra import terraform


@pytest.fixture(autouse=True)
def isolate_infra_environment(monkeypatch):
    # main() writes these directly. Register them so teardown restores even an
    # absent variable, rather than leaking a deployment profile into later tests.
    for key, default in {
        "AWS_PROFILE": "box-hackathon",
        "AWS_DEFAULT_REGION": "us-east-2",
        "TF_VAR_aws_profile": "box-hackathon",
        "TF_VAR_name_prefix": "kloop-test",
    }.items():
        monkeypatch.setenv(key, os.environ.get(key, default))


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


def test_destroy_does_not_delete_table_if_creator_is_pending(monkeypatch):
    from unittest.mock import Mock

    from kloop.cleanup import CleanupLedger
    from scripts import infra

    calls = []

    def run(directory, *args, capture=False):
        calls.append((directory, args))
        if args[:2] == ("output", "-raw"):
            return "kloop-test-123-tfstate"
        if args == ("state", "pull"):
            return """{"resources":[{"type":"aws_dynamodb_table","name":"records",
                "instances":[{"index_key":"cleanup_ledger",
                "attributes":{"name":"owned-ledger"}}]}]}"""
        return None

    monkeypatch.setattr(infra, "terraform", run)
    monkeypatch.setattr(infra.boto3, "Session", lambda **kwargs: Mock())
    monkeypatch.setattr(
        CleanupLedger,
        "entries",
        lambda _self: [
            {
                "key": "active",
                "kind": "bedrock_import",
                "deployment": "kloop-test",
                "resource_id": None,
            }
        ],
    )
    monkeypatch.setattr(sys, "argv", ["infra.py", "destroy"])
    monkeypatch.setenv("NAME_PREFIX", "kloop-test")
    with pytest.raises(RuntimeError, match="Reconcile"):
        infra.main()
    assert not any(args[0] == "destroy" for _, args in calls)


@pytest.fixture
def infra_command(tmp_path, monkeypatch):
    import json
    from unittest.mock import Mock

    from scripts import infra

    outputs = {
        key: {"value": value}
        for key, value in {
            "web_bucket": "kloop-test-web",
            "distribution_id": "distribution",
            "url": "https://example.cloudfront.net",
            "api_endpoint": "https://direct.example",
        }.items()
    }
    monkeypatch.setattr(infra, "ROOT", tmp_path)
    (tmp_path / "infra/evidence").mkdir(parents=True)
    (tmp_path / ".build").mkdir()
    (tmp_path / ".build/package-size.json").write_text("{}")
    session = Mock()
    monkeypatch.setattr(infra.boto3, "Session", lambda **kwargs: session)
    monkeypatch.setattr(
        infra,
        "terraform",
        lambda directory, *args, **kwargs: (
            "kloop-test-state" if args[:2] == ("output", "-raw") else json.dumps(outputs)
        ),
    )
    monkeypatch.setenv("NAME_PREFIX", "kloop-test")
    return infra, session, outputs


def test_deploy_uploads_assets_before_html_and_waits_for_entry_invalidation(
    infra_command, monkeypatch
):
    from unittest.mock import Mock

    infra, session, outputs = infra_command
    web = infra.ROOT / "web/dist"
    (web / "assets").mkdir(parents=True)
    # Create HTML first: filesystem order must not decide publication order.
    (web / "index.html").write_text('<script src="/assets/new.js"></script>')
    (web / "assets/new.js").write_text("new build")
    s3, cloudfront = Mock(), Mock()
    cloudfront.create_invalidation.return_value = {"Invalidation": {"Id": "refresh"}}
    session.client.side_effect = lambda service: {"s3": s3, "cloudfront": cloudfront}[service]
    monkeypatch.setattr(sys, "argv", ["infra.py", "deploy"])
    infra.main()
    uploads = s3.upload_file.call_args_list
    assert [call.args[2] for call in uploads] == ["assets/new.js", "index.html"]
    assert uploads[-1].kwargs["ExtraArgs"]["CacheControl"] == "no-cache, no-store, must-revalidate"
    assert "immutable" in uploads[0].kwargs["ExtraArgs"]["CacheControl"]
    invalidation = cloudfront.create_invalidation.call_args.kwargs
    assert invalidation["DistributionId"] == "distribution"
    assert invalidation["InvalidationBatch"]["Paths"] == {
        "Quantity": 2,
        "Items": ["/", "/index.html"],
    }
    cloudfront.get_waiter.assert_any_call("invalidation_completed")
    cloudfront.get_waiter.return_value.wait.assert_called_with(
        DistributionId="distribution", Id="refresh"
    )


def test_smoke_uses_product_routes_and_never_reports_credentials(
    infra_command, monkeypatch, capsys
):
    import io
    import json
    from unittest.mock import Mock
    from urllib.error import HTTPError
    from urllib.request import Request

    infra, session, outputs = infra_command
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 200
    response.read.return_value = json.dumps(
        {"models": {"without": None}, "csrf_token": "test-token"}
    ).encode()
    opener = Mock()
    opener.open.return_value = response
    session.client.return_value.get_secret_value.return_value = {
        "SecretString": "test-only-password"
    }
    requests = []

    def urlopen(request, **kwargs):
        requests.append(request)
        if isinstance(request, str) and request.endswith("/api/session"):
            code = 403 if request.startswith("https://direct") else 401
            raise HTTPError(request, code, "expected denial", {}, io.BytesIO())
        return response

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: opener)
    monkeypatch.setattr(sys, "argv", ["infra.py", "smoke"])
    infra.main()
    assert requests == [
        "https://example.cloudfront.net",
        "https://example.cloudfront.net/api/session",
        "https://direct.example/api/session",
    ]
    login, serving = [call.args[0] for call in opener.open.call_args_list]
    assert isinstance(login, Request) and login.full_url.endswith("/api/login")
    assert serving == "https://example.cloudfront.net/api/serving"
    report = json.loads((infra.ROOT / "infra/evidence/product-smoke.json").read_text())
    assert report["unauthenticated_status"] == 401 and report["direct_api_status"] == 403
    assert report["authenticated_serving_status"] == 200
    assert "test-only-password" not in capsys.readouterr().out
