"""Deployment-owned external resource ledger, shared by creators and destroy.

Reserve a deterministic import/job name before creation. Resolve to an ARN (or
webhook ID) after creation, including after an uncertain response. Never delete a
pending row: reconcile it first. All rows use the canonical DynamoStorage keys.
"""

import json
from typing import Any

from boto3.dynamodb.conditions import Attr

from kloop.adapters.aws import DynamoStorage


class CleanupLedger:
    def __init__(self, table: Any, deployment: str):
        self.storage = DynamoStorage(table)
        self.deployment = deployment
        self.collection = f"cleanup:{deployment}"

    @property
    def fence_key(self):
        return {"pk": f"cleanup-control:{self.deployment}", "sk": "destroy"}

    def fence(self) -> None:
        """Permanently stop new reservations before taking a cleanup snapshot.

        Pre-fence creators retain their pending rows and may finish resolving.
        Never expire this fence or a reservation: uncertain creates need explicit
        reconciliation. A destroyed deployment must use a fresh ledger table.
        """
        self.storage._table.put_item(Item=self.fence_key)

    def reserve(self, key: str, kind: str, name: str) -> None:
        """Must succeed BEFORE the external create; resolve is its final step."""
        if kind not in {"bedrock_import", "box_webhook", "sagemaker_training"}:
            raise ValueError("Unsupported cleanup resource")
        table = self.storage._table
        table.meta.client.transact_write_items(
            TransactItems=[
                {
                    "ConditionCheck": {
                        "TableName": table.name,
                        "Key": self.fence_key,
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": table.name,
                        "Item": {
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
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
            ]
        )

    def resolve(self, key: str, resource_id: str) -> None:
        if not resource_id:
            raise ValueError("A resource identity is required")
        table = self.storage._table
        item = table.get_item(Key={"pk": self.collection, "sk": key}, ConsistentRead=True).get(
            "Item"
        )
        if item is None:
            raise KeyError(key)
        row = json.loads(item["payload"])
        if row["resource_id"] not in (None, resource_id):
            raise ValueError("Cleanup reservation already resolves to another resource")
        row["resource_id"] = resource_id
        table.put_item(
            Item={**item, "payload": json.dumps(row)},
            ConditionExpression=Attr("payload").eq(item["payload"]),
        )

    def remove(self, row) -> None:
        self.storage._table.delete_item(
            Key={"pk": self.collection, "sk": row["key"]},
            ConditionExpression=Attr("payload").eq(json.dumps(row)),
        )

    def entries(self):
        return self.storage.list(self.collection)


def cleanup(ledger: CleanupLedger, session: Any, delete_webhook=None) -> None:
    """Fail closed on unresolved ownership; retain rows on any deletion failure.

    delete_webhook is the Box adapter's idempotent delete callback. Production
    destroy refuses to proceed if Box cleanup is needed without that adapter.
    """
    ledger.fence()
    rows = ledger.entries()
    for row in rows:
        if row.get("deployment") != ledger.deployment or not row.get("resource_id"):
            raise RuntimeError(f"Reconcile cleanup entry before destroy: {row['key']}")
    bedrock = session.client("bedrock")
    identity = session.client("sts").get_caller_identity()["Account"]
    for row in rows:
        resource = row["resource_id"]
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
        elif row["kind"] == "sagemaker_training":
            expected = f"arn:aws:sagemaker:us-east-2:{identity}:training-job/"
            if resource != expected + row["name"]:
                raise ValueError("Training ARN is outside this project or selected Region")
            sagemaker = session.client("sagemaker")
            try:
                job = sagemaker.describe_training_job(TrainingJobName=row["name"])
                if job["TrainingJobStatus"] == "InProgress":
                    sagemaker.stop_training_job(TrainingJobName=row["name"])
            except sagemaker.exceptions.ResourceNotFound:
                pass
        elif row["kind"] == "box_webhook":
            if delete_webhook is None:
                raise RuntimeError("Box webhook cleanup adapter required before destroy")
            delete_webhook(resource)
        else:
            raise ValueError("Unknown cleanup kind")
        ledger.remove(row)
    if ledger.entries():
        raise RuntimeError("Cleanup ledger is not empty; retain the table and retry")
