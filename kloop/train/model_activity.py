"""Evaluation model pins shared with explicit unload operations."""

import os
import time
from contextlib import contextmanager
from uuid import uuid4

from kloop.train.loading import ModelGuard
from kloop.train.state import DynamoTrainingStore


@contextmanager
def evaluation_pin(aws, event):
    store = DynamoTrainingStore(aws.resource("dynamodb").Table(os.environ["KLOOP_VERSIONS_TABLE"]))
    id = uuid4().hex
    with ModelGuard(store.table)():
        arns = {event["candidate_arn"]}
        previous = event.get("expected_current_version")
        if previous:
            version = store.get(previous)
            if not version or not version.import_arn:
                raise ValueError("Evaluation baseline is not loaded")
            arns.add(version.import_arn)
        # Refuse an ARN whose unload has already been admitted.
        for version in store.versions():
            operation = version.manifest.get("loading", {})
            if operation.get("action") == "unload" and operation.get("arn") in arns:
                raise ValueError("Evaluation model is unloading")
        store.storage.put(
            "model_activity", id, {"arns": sorted(arns), "until": int(time.time()) + 930}
        )
    try:
        yield
    finally:
        store.table.delete_item(Key={"pk": "model_activity", "sk": id})
