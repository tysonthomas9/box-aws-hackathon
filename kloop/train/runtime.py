"""AWS wiring loaded at invocation only; no credentials needed to import modules."""

import json
import os
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from kloop.adapters.aws import DynamoStorage, S3Artifacts
from kloop.answer import Answerer
from kloop.answer.bedrock import ImportedModelClient
from kloop.box.auth import token_provider
from kloop.box.client import BoxClient, sdk_client
from kloop.cleanup import CleanupLedger
from kloop.config import Settings
from kloop.extract.runtime import factory as extraction_factory
from kloop.extract.runtime import snapshot_storage
from kloop.train.config import TrainingConfig
from kloop.train.data import DataBuilder
from kloop.train.helpers import TrainingHelpers
from kloop.train.resources import ImportSlots, protected_ask_models
from kloop.train.service import DispatchRejected, TrainingService
from kloop.train.serving import ServingBackends
from kloop.train.state import DynamoTrainingStore
from kloop.train.worker import TrainingWorker


class Dispatch:
    def __init__(self, client, state_machine):
        self.client, self.state_machine = client, state_machine

    def __call__(self, version_id):
        try:
            self.client.start_execution(
                stateMachineArn=self.state_machine,
                name=version_id,
                input=json.dumps({"version_id": version_id}),
            )
        except self.client.exceptions.ExecutionAlreadyExists:
            # Name is derived solely from the idempotency token. A terminal prior
            # execution is not restarted under the same token.
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
                raise DispatchRejected("Training execution was refused") from exc
            raise


def session():
    return boto3.Session(region_name="us-east-2")


def store_for(session):
    return DynamoTrainingStore(
        session.resource("dynamodb").Table(os.environ["KLOOP_VERSIONS_TABLE"])
    )


def service(session):
    return TrainingService(
        store_for(session),
        extraction_factory(session),
        Dispatch(session.client("stepfunctions"), os.environ["KLOOP_TRAINING_ARN"]),
        TrainingConfig(),
        snapshots=snapshot_storage(session),
    )


def warmup_answerer(session, *, clock=time.monotonic, sleep=time.sleep):
    # Reserve the last minute of the 15-minute Lambda/ASL window for the
    # final transport attempt and invocation overhead; never stack SDK retries.
    runtime = session.client(
        "bedrock-runtime",
        config=Config(
            connect_timeout=5,
            read_timeout=45,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )
    return Answerer(ImportedModelClient(runtime), retry_seconds=840, clock=clock, sleep=sleep)


def factory(session):
    config, settings = TrainingConfig(), Settings()
    store = store_for(session)
    artifacts = S3Artifacts(session.client("s3"), settings.artifact_bucket)
    sdk = sdk_client(token_provider(session.client("secretsmanager"), settings))
    box = BoxClient(sdk, settings.box_folder_id)
    reports = os.environ["KLOOP_REPORTS_FOLDER_ID"]

    def write(key, data, content_type):
        # Content-addressed keys/names make retries reviewable. Box upload itself
        # is reconciled by filename before creating a second report.
        artifacts.put(key, data, content_type)
        name = key.replace("/", "-")
        existing = [f for f in box.list_folder(reports) if f.name == name]
        if len(existing) > 1:
            raise ValueError("Duplicate training report names require reconciliation")
        if existing:
            if box.download_text(existing[0].id) != data.decode():
                raise ValueError("Box report differs from immutable training artifact")
        else:
            box.upload_text(name, data.decode(), folder_id=reports)

    runtime = session.client(
        "bedrock-runtime",
        config=Config(
            connect_timeout=5,
            read_timeout=180,
            retries={"total_max_attempts": 2, "mode": "adaptive"},
        ),
    )
    helpers = TrainingHelpers(runtime, artifacts)
    ledger = CleanupLedger(
        session.resource("dynamodb").Table(os.environ["KLOOP_CLEANUP_LEDGER_TABLE"]),
        config.deployment,
    )

    asks = DynamoStorage(session.resource("dynamodb").Table(os.environ["KLOOP_ASK_JOBS_TABLE"]))

    def protected():
        arns = {settings.base_model_id} | protected_ask_models(asks, int(time.time()))
        current = store.get(store.current()) if store.current() else None
        if current and current.import_arn:
            arns.add(current.import_arn)
        return arns

    slots = ImportSlots(session.client("bedrock"), ledger, protected)

    def evaluate(**request):
        from kloop.eval import GateDecision

        response = session.client("lambda", config=Config(read_timeout=900)).invoke(
            FunctionName=os.environ["KLOOP_EVALUATION_FUNCTION"],
            Payload=json.dumps(request).encode(),
        )
        with response["Payload"] as body:
            payload = json.loads(body.read())
        if response.get("FunctionError"):
            raise RuntimeError("Evaluation Lambda failed; candidate cannot be promoted")
        if request.get("action") == "audit":
            return payload
        return GateDecision.model_validate(payload)

    serving = ServingBackends({"bedrock": warmup_answerer(session)})
    snapshots = snapshot_storage(session)
    return TrainingWorker(
        store,
        snapshots,
        DataBuilder(helpers.generate, helpers.check, write),
        slots,
        ledger,
        session.client("sagemaker"),
        artifacts,
        serving,
        evaluate,
        bucket=settings.artifact_bucket,
        training_role=os.environ["KLOOP_SAGEMAKER_ROLE"],
        import_role=os.environ["KLOOP_IMPORT_ROLE"],
        dev_bytes=Path(config.dev_path).read_bytes(),
        helpers=helpers,
    )


def handler(event, context):
    aws = session()
    if event.get("recover_expired"):
        store = store_for(aws)
        lock = store.lock()
        if not lock or int(time.time()) < lock["until"]:
            return {"recovered": False}
        states = aws.client("stepfunctions")
        arn = os.environ["KLOOP_TRAINING_ARN"].replace(":stateMachine:", ":execution:")
        try:
            execution = states.describe_execution(executionArn=f"{arn}:{lock['owner']}")
        except states.exceptions.ExecutionDoesNotExist:
            # Expired lease + absent deterministic execution proves dispatch never
            # started. No workflow could have reached resource creation.
            version = store.get(lock["owner"])
            if version is not None and version.status != "pending":
                raise RuntimeError(
                    "Missing execution for a started version requires reconciliation"
                ) from None
            if version is not None:
                version.status = "failed"
                store.save(version)
            store.release(lock["owner"])
            return {"recovered": True}
        if execution["status"] == "RUNNING":
            return {"recovered": False}
        worker = factory(aws)
        if not worker.recover(lock["owner"], execution["status"], int(time.time())):
            raise RuntimeError("Expired training cleanup still pending")
        return {"recovered": True}
    worker = factory(aws)
    if "detail" in event:
        detail = event["detail"]
        execution = aws.client("stepfunctions").describe_execution(
            executionArn=detail["executionArn"]
        )
        version_id = json.loads(execution["input"])["version_id"]
        if not worker.recover(version_id, execution["status"], int(time.time())):
            raise RuntimeError("Training cleanup still pending; retry recovery")
        return {"recovered": True}
    return worker.handle(event["action"], event["version_id"], batch=event.get("batch"))
