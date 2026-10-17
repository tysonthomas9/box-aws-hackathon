"""Deployment-owned external resource ledger, shared by creators and destroy.

Reserve a deterministic import/job name before creation. Resolve to an ARN (or
webhook ID) after creation, including after an uncertain response. Never delete a
pending row: reconcile it first. All rows use the canonical DynamoStorage keys.
"""

import json
from typing import Any

from kloop.adapters.aws import DynamoStorage


class CleanupLedger:
    def __init__(self, table: Any, deployment: str):
        self.storage = DynamoStorage(table)
        self.deployment = deployment
        self.collection = f"cleanup:{deployment}"

    def reserve(self, key: str, kind: str, name: str) -> None:
        if kind not in {"bedrock_import", "box_webhook"}:
            raise ValueError("Unsupported cleanup resource")
        self.storage._table.put_item(
            Item={
                "pk": self.collection,
                "sk": key,
                "payload": json.dumps(
                    {
                        "key": key,
                        "deployment": self.deployment,
                        "kind": kind,
                        "name": name,
                        "resource_id": None,
                    }
                ),
            },
            ConditionExpression="attribute_not_exists(pk)",
        )

    def resolve(self, key: str, resource_id: str) -> None:
        row = self.storage.get(self.collection, key)
        if row is None:
            raise KeyError(key)
        row["resource_id"] = resource_id
        self.storage.put(self.collection, key, row)

    def entries(self):
        return self.storage.list(self.collection)


def cleanup(ledger: CleanupLedger, session: Any, delete_webhook=None) -> None:
    """Fail closed on unresolved ownership; retain rows on any deletion failure.

    delete_webhook is the Box adapter's idempotent delete callback. Production
    destroy refuses to proceed if Box cleanup is needed without that adapter.
    """
    bedrock = session.client("bedrock")
    identity = session.client("sts").get_caller_identity()["Account"]
    for row in ledger.entries():
        resource = row.get("resource_id")
        if row.get("deployment") != ledger.deployment or not resource:
            raise RuntimeError(f"Reconcile cleanup entry before destroy: {row['key']}")
        if row["kind"] == "bedrock_import":
            expected = f"arn:aws:bedrock:us-east-2:{identity}:imported-model/"
            if not resource.startswith(expected):
                raise ValueError("Cleanup ARN is outside this project or selected Region")
            try:
                tags = bedrock.list_tags_for_resource(resourceARN=resource)["tags"]
                labels = {tag["key"]: tag["value"] for tag in tags}
                if labels.get("deployment") != ledger.deployment:
                    raise ValueError("Import is not tagged for this deployment")
                bedrock.delete_imported_model(modelIdentifier=resource)
            except bedrock.exceptions.ResourceNotFoundException:
                pass
        elif row["kind"] == "box_webhook":
            if delete_webhook is None:
                raise RuntimeError("Box webhook cleanup adapter required before destroy")
            delete_webhook(resource)
        else:
            raise ValueError("Unknown cleanup kind")
        ledger.storage.delete(ledger.collection, row["key"])
