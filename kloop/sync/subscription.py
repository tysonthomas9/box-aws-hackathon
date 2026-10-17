"""Deployment seed hook; destroy already uses the shared cleanup ledger."""

from kloop.box.client import BoxClient
from kloop.cleanup import CleanupLedger


def seed_webhook(box: BoxClient, ledger: CleanupLedger, address: str) -> str:
    key = f"box-webhook:{box.folder_id}"
    existing = next((r for r in ledger.entries() if r["key"] == key), None)
    if existing:
        if not existing["resource_id"]:
            raise RuntimeError("Reconcile pending webhook creation before seeding again")
        hook = box.sdk.webhooks.get_webhook_by_id(existing["resource_id"])
        if (
            not hook.target
            or hook.target.id != box.folder_id
            or hook.target.type != "folder"
            or hook.address != address
            or not {"FILE.UPLOADED", "FILE.TRASHED", "FILE.DELETED"}.issubset(hook.triggers)
        ):
            raise ValueError("Existing webhook does not match seed configuration")
        return existing["resource_id"]
    ledger.reserve(key, "box_webhook", box.folder_id)
    webhook_id = box.create_webhook(address)
    hook = box.sdk.webhooks.get_webhook_by_id(webhook_id)
    if (
        not hook.target
        or hook.target.id != box.folder_id
        or hook.target.type != "folder"
        or hook.address != address
        or not {"FILE.UPLOADED", "FILE.TRASHED", "FILE.DELETED"}.issubset(hook.triggers)
    ):
        raise ValueError("Created webhook verification failed; reconcile the pending ledger row")
    ledger.resolve(key, webhook_id)  # Final step, after every verification succeeds.
    return webhook_id
