"""Run `make seed` or `make box-smoke`; never print SDK errors containing credentials."""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import boto3
from box_sdk_gen.box.errors import BoxAPIError
from box_sdk_gen.managers.folders import CreateFolderParent

from kloop.box.auth import token_provider
from kloop.box.client import BoxClient, sdk_client
from kloop.box.seed import DEFAULT_PACK, seed
from kloop.cleanup import CleanupLedger
from kloop.config import Settings
from kloop.sync.subscription import seed_webhook


def runtime(settings: Settings, mode: str):
    session = boto3.Session(region_name=settings.region)
    secrets = session.client("secretsmanager")
    return sdk_client(token_provider(secrets, settings, mode=mode))


def smoke(sdk, settings: Settings, *, webhook_url: str = "") -> dict:
    """An isolated live test. Only objects created by this call are cleaned up.

    A deployed webhook URL is optional until the API exists. Registration alone
    does not prove delivery/signature verification. No temporary public receiver
    is deployed here; the integration task owns that proof.
    """
    actor = sdk.users.get_user_me(fields=["id"])
    folder = sdk.folders.create_folder("kloop-smoke-" + uuid4().hex, CreateFolderParent("0"))
    result = {"folder_id": folder.id, "actor_id": actor.id, "checks": {}, "cleanup": False}
    client = BoxClient(sdk, folder.id)
    hook = None
    files = []
    try:
        original = client.upload_text("smoke.txt", "The Kestrel service owner is Mira Solven.\n")
        files.append(original.file_id)
        result["file_id"] = original.file_id
        if client.get_document(original.file_id, original.version_id).text != (
            "The Kestrel service owner is Mira Solven.\n"
        ):
            raise RuntimeError("Smoke download did not match upload")
        result["checks"]["upload_download"] = "passed"
        if len(client.list_documents(folder.id)) != 1:
            raise RuntimeError("Smoke folder listing did not contain one document")
        result["checks"]["list"] = "passed"
        revised = client.upload_version(
            original.file_id,
            "The Kestrel service owner is test-only.\n",
            expected_etag=original.etag,
        )
        if revised.version_id == original.version_id:
            raise RuntimeError("Smoke version did not change")
        if "Mira Solven" not in client.get_document(original.file_id, original.version_id).text:
            raise RuntimeError("Smoke old-version download changed")
        if client.get_document(revised.file_id, revised.version_id).text != (
            "The Kestrel service owner is test-only.\n"
        ):
            raise RuntimeError("Smoke new-version download did not match upload")
        result["versions"] = {"original": original.version_id, "revised": revised.version_id}
        result["checks"]["versions"] = "passed"
        # Smoke-only transport probe, not extraction business logic or acceptance.
        from box_sdk_gen import AiAgentExtractStructured, AiItemBase
        from box_sdk_gen.managers.ai import CreateAiExtractStructuredFields

        response = sdk.ai.create_ai_extract_structured(
            [AiItemBase(id=original.file_id, type="file")],
            fields=[
                CreateAiExtractStructuredFields(
                    key="owner", type="string", prompt="Who owns the Kestrel service?"
                )
            ],
            ai_agent=AiAgentExtractStructured.from_dict(
                {
                    "type": "ai_agent_extract_structured",
                    "basic_text": {"model": "aws__claude_4_5_haiku"},
                    "long_text": {"model": "aws__claude_4_5_haiku"},
                }
            ),
        )
        if not response.answer:
            raise RuntimeError("Smoke extraction returned no answer")
        answer = json.dumps(response.answer.to_dict()).lower()
        if "test-only" not in answer:
            raise RuntimeError("Smoke extraction did not reflect the revised owner")
        result["checks"]["extract_transport"] = "passed"
        result["checks"]["extract_comparison"] = "passed"
        if webhook_url:
            hook = client.create_webhook(webhook_url)
            actual = sdk.webhooks.get_webhook_by_id(hook)
            if actual.target.id != folder.id:
                raise RuntimeError("Smoke webhook targets the wrong folder")
            result["checks"]["webhook_registration"] = "passed"
        else:
            result["checks"]["webhook_registration"] = "skipped: no deployed webhook URL"
        result["checks"]["signed_delivery"] = (
            "not tested: requires deployed receiver and signing keys"
        )
    finally:
        if hook:
            client.delete_webhook(hook)
        for file_id in files:
            client.delete_file(file_id)
        # Non-recursive delete: never remove unexpected content introduced by another actor.
        sdk.folders.delete_folder_by_id(folder.id)
        try:
            sdk.folders.get_folder_by_id(folder.id, fields=["id"])
        except BoxAPIError as exc:
            if exc.response_info.status_code != 404:
                raise
        else:
            raise RuntimeError("Smoke folder still exists after cleanup")
        result["cleanup"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["seed", "smoke"])
    parser.add_argument("--auth", choices=["ccg", "developer"], default="ccg")
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--webhook-url", default=os.getenv("KLOOP_BOX_WEBHOOK_URL", ""))
    args = parser.parse_args()
    try:
        settings = Settings()
        sdk = runtime(settings, args.auth)
        if args.command == "smoke":
            result = smoke(sdk, settings, webhook_url=args.webhook_url)
        else:
            ledger = None
            if args.webhook_url:
                session = boto3.Session(region_name=settings.region)
                ledger = CleanupLedger(
                    session.resource("dynamodb").Table(os.environ["KLOOP_CLEANUP_LEDGER_TABLE"]),
                    os.environ["NAME_PREFIX"],
                )
            folder_id = settings.box_folder_id
            if not folder_id:
                # Caller must retain the returned id in KLOOP_BOX_FOLDER_ID for future runs.
                folder_id = sdk.folders.create_folder("Halvard Systems", CreateFolderParent("0")).id
                print(json.dumps({"created_folder_id": folder_id}), flush=True)
            box = BoxClient(sdk, folder_id)
            result = seed(box, args.pack)
            if ledger is not None:
                result["webhook_id"] = seed_webhook(box, ledger, args.webhook_url)
        print(json.dumps(result, indent=2))
        return 0
    except BoxAPIError as exc:
        if exc.response_info.status_code == 412:
            print(
                "Box file changed by someone else. Stopped; re-read before seeding.",
                file=sys.stderr,
            )
        else:
            print(
                f"Box {args.command} failed (HTTP {exc.response_info.status_code}).",
                file=sys.stderr,
            )
        return 1
    except Exception as exc:
        # Box SDK exceptions can contain request headers, bodies, and signed URLs.
        # CLI emits only the class; callers debugging locally can inspect safely.
        print(
            f"Box {args.command} failed ({type(exc).__name__}); check auth and permissions.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
