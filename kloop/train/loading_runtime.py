"""AWS composition for reloads; no clients or credentials at module import."""

import json
import os
import time
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from kloop.adapters.aws import DynamoStorage, S3Artifacts
from kloop.cleanup import CleanupLedger
from kloop.train.loading import ModelGuard, VersionLoading
from kloop.train.resources import ImportSlots, protected_ask_models
from kloop.train.runtime import warmup_answerer
from kloop.train.service import DispatchRejected
from kloop.train.state import DynamoTrainingStore
from kloop.train.weights import record_weights, verify_weights


def service(aws):
    dynamo = aws.resource("dynamodb")
    store = DynamoTrainingStore(dynamo.Table(os.environ["KLOOP_VERSIONS_TABLE"]))
    asks = DynamoStorage(dynamo.Table(os.environ["KLOOP_ASK_JOBS_TABLE"]))
    ledger = CleanupLedger(
        dynamo.Table(os.environ["KLOOP_CLEANUP_LEDGER_TABLE"]), os.environ["KLOOP_TRAIN_DEPLOYMENT"]
    )
    bedrock = aws.client(
        "bedrock",
        config=Config(connect_timeout=5, read_timeout=15, retries={"total_max_attempts": 2}),
    )
    s3 = aws.client("s3")
    bucket = os.environ["KLOOP_ARTIFACT_BUCKET"]

    def protected():
        arns = {os.getenv("KLOOP_BASE_MODEL_ID"), os.getenv("KLOOP_TEMPORARY_TRAINED_MODEL_ARN")}
        arns |= protected_ask_models(asks, int(time.time()))
        for version in store.versions():
            if (
                version.id == store.current()
                or version.status == "evaluating"
                or version.manifest.get("retain_for_medical_report")
            ):
                arns.add(version.import_arn)
        for row in store.storage.list("model_activity"):
            if row["until"] > time.time():
                arns.update(row["arns"])
        return arns

    states = aws.client("stepfunctions")

    def dispatch(id, owner):
        # A lost reply retains the lock; retrying this exact name is idempotent.
        try:
            states.start_execution(
                stateMachineArn=os.environ["KLOOP_LOADING_ARN"],
                name=owner,
                input=json.dumps({"version_id": id, "owner": owner}),
            )
        except states.exceptions.ExecutionAlreadyExists:
            pass
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {
                "AccessDeniedException",
                "StateMachineDoesNotExist",
                "StateMachineDeleting",
                "InvalidArn",
                "InvalidExecutionInput",
                "ExecutionLimitExceeded",
            }:
                raise DispatchRejected("Load workflow was refused") from exc
            raise

    def weights(version, verify):
        if verify:
            return verify_weights(version, s3, bucket)
        return record_weights(version, S3Artifacts(s3, bucket), bucket)

    return VersionLoading(
        store,
        ImportSlots(bedrock, ledger, protected),
        dispatch,
        ModelGuard(store.table),
        weights,
        clock=time.time,
        protected=protected,
        import_role=os.environ["KLOOP_IMPORT_ROLE"],
        warm=lambda arn: warmup_answerer(aws).warm_up(arn),
    )


@lru_cache(maxsize=1)
def runtime():
    return service(boto3.Session(region_name="us-east-2"))


def handler(event, context):
    loader = runtime()
    if "detail" in event:
        states = boto3.Session(region_name="us-east-2").client("stepfunctions")
        execution = states.describe_execution(executionArn=event["detail"]["executionArn"])
        if execution["status"] not in {"FAILED", "TIMED_OUT", "ABORTED"}:
            return {}
        request = json.loads(execution["input"])
        if (loader.store.lock() or {}).get("owner") != request["owner"]:
            return {}
        result = loader.step("fail", request["version_id"], request["owner"])
        if not result["complete"]:
            raise RuntimeError("Import cleanup pending; retry recovery")
        return result
    return loader.step(event["action"], event["version_id"], event["owner"])
