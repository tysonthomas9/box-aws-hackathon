"""Deploy commands. Real credentials are never Terraform inputs or log output."""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import UTC
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]


def terraform(directory, *args, capture=False):
    # The credential process retains Expiration and can refresh during long CF deletes.
    profile = os.getenv("AWS_PROFILE", "box-hackathon")
    original_config = os.getenv("AWS_CONFIG_FILE", str(Path.home() / ".aws/config"))
    original_credentials = os.getenv(
        "AWS_SHARED_CREDENTIALS_FILE", str(Path.home() / ".aws/credentials")
    )
    command = shlex.join(
        [
            "env",
            f"AWS_CONFIG_FILE={original_config}",
            f"AWS_SHARED_CREDENTIALS_FILE={original_credentials}",
            shutil.which("aws") or "aws",
            "configure",
            "export-credentials",
            "--profile",
            profile,
            "--format",
            "process",
        ]
    )
    with tempfile.NamedTemporaryFile(mode="w", prefix="kloop-aws-config-", dir="/tmp") as config:
        section = "default" if profile == "default" else f"profile {profile}"
        config.write(f"[{section}]\nregion = us-east-2\ncredential_process = {command}\n")
        config.flush()
        environment = dict(os.environ, AWS_CONFIG_FILE=config.name)
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            environment.pop(key, None)
        result = subprocess.run(
            [os.getenv("TERRAFORM", "terraform"), f"-chdir={directory}", *args],
            check=True,
            text=True,
            capture_output=capture,
            env=environment,
        )
    return result.stdout if capture else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["bootstrap", "plan", "deploy", "destroy", "smoke"])
    args = parser.parse_args()
    profile = os.getenv("AWS_PROFILE", "box-hackathon")
    prefix = os.getenv("NAME_PREFIX", "kloop")
    os.environ["TF_VAR_aws_profile"] = profile
    os.environ["TF_VAR_name_prefix"] = prefix
    os.environ["AWS_PROFILE"] = profile
    os.environ["AWS_DEFAULT_REGION"] = "us-east-2"
    session = boto3.Session(profile_name=profile, region_name="us-east-2")
    if args.command == "bootstrap":
        terraform("infra/bootstrap", "init", "-input=false")
        terraform("infra/bootstrap", "apply", "-auto-approve", "-input=false")
    bucket = terraform("infra/bootstrap", "output", "-raw", "state_bucket", capture=True).strip()
    if not bucket.startswith(f"{prefix}-"):
        raise RuntimeError("State bucket belongs to another deployment")
    terraform(
        "infra",
        "init",
        "-reconfigure",
        "-input=false",
        f"-backend-config=bucket={bucket}",
        f"-backend-config=key={prefix}/terraform.tfstate",
        "-backend-config=region=us-east-2",
        "-backend-config=use_lockfile=true",
        "-backend-config=encrypt=true",
    )
    if args.command == "bootstrap":
        return
    if args.command == "plan":
        terraform("infra", "validate")
        terraform("infra", "plan", "-input=false")
        return
    if args.command == "deploy":
        terraform("infra", "apply", "-auto-approve", "-input=false")
        outputs = json.loads(terraform("infra", "output", "-json", capture=True))
        s3 = session.client("s3")
        web = ROOT / "web" / "dist"
        if web.is_dir() and (web / "index.html").is_file():
            import mimetypes

            for file in web.rglob("*"):
                if file.is_file():
                    s3.upload_file(
                        str(file),
                        outputs["web_bucket"]["value"],
                        str(file.relative_to(web)),
                        ExtraArgs={
                            "ContentType": mimetypes.guess_type(file.name)[0]
                            or "application/octet-stream"
                        },
                    )
        else:
            s3.upload_file(
                str(ROOT / "infra/placeholder.html"),
                outputs["web_bucket"]["value"],
                "index.html",
                ExtraArgs={"ContentType": "text/html"},
            )
        session.client("cloudfront").get_waiter("distribution_deployed").wait(
            Id=outputs["distribution_id"]["value"]
        )
        print(outputs["url"]["value"])
        return
    if args.command == "smoke":
        outputs = json.loads(terraform("infra", "output", "-json", capture=True))
        from datetime import datetime
        from urllib.error import HTTPError
        from urllib.request import urlopen

        url = outputs["url"]["value"]
        with urlopen(f"{url}/api/health", timeout=30) as response:
            health = json.load(response)
        with urlopen(url, timeout=30) as response:
            static_status = response.status
        try:
            urlopen(f"{outputs['api_endpoint']['value']}/api/health", timeout=30)
        except HTTPError as error:
            direct_status = error.code
        else:
            raise RuntimeError("Direct API request bypassed the origin guard")
        if direct_status != 403 or health.get("status") != "placeholder":
            raise RuntimeError("Placeholder smoke failed")
        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "deployment": prefix,
            "url": url,
            "cloudfront_health": health,
            "static_status": static_status,
            "direct_api_status": direct_status,
            "package": json.loads((ROOT / ".build/package-size.json").read_text()),
        }
        (ROOT / "infra/evidence/placeholder-smoke.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report))
        return
    # Outputs may already be gone after an interrupted destroy. Locate the ledger
    # in Terraform's recovered state; never guess whether an untracked table is ours.
    state = json.loads(terraform("infra", "state", "pull", capture=True))
    ledger_names = [
        item["attributes"]["name"]
        for resource in state.get("resources", [])
        if resource["type"] == "aws_dynamodb_table" and resource["name"] == "records"
        for item in resource.get("instances", [])
        if item.get("index_key") == "cleanup_ledger"
    ]
    if ledger_names:
        from kloop.cleanup import CleanupLedger, cleanup

        table = session.resource("dynamodb").Table(ledger_names[0])
        ledger = CleanupLedger(table, prefix)
        ledger.fence()
        delete_webhook = None
        if any(row["kind"] == "box_webhook" for row in ledger.entries()):
            from box_sdk_gen.box.errors import BoxAPIError

            from kloop.box import BoxClient, sdk_client, token_provider
            from kloop.config import Settings

            settings = Settings()
            client = BoxClient(
                sdk_client(token_provider(session.client("secretsmanager"), settings)),
                settings.box_folder_id,
            )

            def delete_webhook(webhook_id):
                try:
                    client.delete_webhook(webhook_id)
                except BoxAPIError as error:
                    if error.response_info.status_code != 404:
                        raise

        cleanup(ledger, session, delete_webhook)
    terraform("infra", "destroy", "-auto-approve", "-input=false")
    terraform("infra/bootstrap", "destroy", "-auto-approve", "-input=false")


if __name__ == "__main__":
    main()
