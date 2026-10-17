"""Deployment composition. Imports are credential-free; clients are lazy per Lambda."""

import importlib
import os
from functools import lru_cache

import boto3
from botocore.config import Config

from kloop.adapters.aws import DynamoStorage
from kloop.answer.bedrock import ImportedModelClient
from kloop.config import Settings
from kloop.schemas import ApprovedSnapshot
from kloop.web.api import Services, create_app
from kloop.web.jobs import DynamoJobs, JobService, SearchEvidence, SQSDispatch, Worker
from kloop.web.security import DynamoThrottle, Security


def session():
    return boto3.Session(region_name=Settings().region)


def plugin(path, aws):
    if ":" not in path:
        raise RuntimeError("Deploy must configure the service factory as module:function")
    module, name = path.split(":", 1)
    return getattr(importlib.import_module(module), name)(aws)


class LazyService:
    def __init__(self, build):
        self.build = lru_cache(maxsize=1)(build)

    def __getattr__(self, name):
        return getattr(self.build(), name)


def jobs(aws):
    table = aws.resource("dynamodb").Table(os.environ["KLOOP_ASK_JOBS_TABLE"])
    client = aws.client(
        "sqs", config=Config(connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 1})
    )
    return JobService(DynamoJobs(table), SQSDispatch(client, os.environ["KLOOP_ASK_QUEUE_URL"]))


@lru_cache(maxsize=1)
def api_runtime():
    from kloop.train.state import DynamoTrainingStore
    from lambdas.sync import compose_ingress

    aws = session()
    secrets = aws.client(
        "secretsmanager",
        config=Config(connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 2}),
    )

    def secret(name):
        return secrets.get_secret_value(SecretId=os.environ[name])["SecretString"]

    security = Security(
        secret("KLOOP_AUTH_SECRET_ID"),
        secret("KLOOP_COOKIE_SECRET_ID"),
        secret("KLOOP_ORIGIN_SECRET_ID"),
        os.environ["KLOOP_PUBLIC_ORIGIN"],
    )
    extraction = LazyService(lambda: plugin(os.environ["KLOOP_EXTRACTION_FACTORY"], aws))
    training = LazyService(lambda: plugin(os.environ["KLOOP_TRAINING_FACTORY"], aws))
    dynamo = aws.resource("dynamodb")
    versions_table = dynamo.Table(os.environ["KLOOP_VERSIONS_TABLE"])
    version_store = DynamoTrainingStore(versions_table)
    cursors = DynamoStorage(dynamo.Table(os.environ["KLOOP_SYNC_CURSORS_TABLE"]))
    results = DynamoStorage(dynamo.Table(os.getenv("KLOOP_REPORTS_TABLE", versions_table.name)))
    ingress = LazyService(lambda: compose_ingress(aws))

    def select_models():
        base = {
            "arn": os.environ["KLOOP_BASE_MODEL_ID"],
            "version_id": os.getenv("KLOOP_BASE_VERSION_ID", "base"),
            "snapshot_sha256": None,
        }
        current_id = version_store.current()
        current = version_store.get(current_id) if current_id else None
        trained = None
        if current and current.status == "promoted":
            if (
                not current.import_arn
                or current.manifest.get("serving_backend", "bedrock") != "bedrock"
            ):
                raise ValueError("Serving version requires a configured Bedrock imported model")
            trained = {
                "arn": current.import_arn,
                "version_id": current.id,
                "snapshot_sha256": current.manifest["snapshot_hash"],
            }
        return {"without": base, "with": trained, "search": base}

    def sources():
        from kloop.sync.service import source_files

        files = {
            f.file_id: {
                "file_id": f.file_id,
                "name": f.name,
                "version_id": f.version_id,
                "retired": False,
            }
            for f in source_files(extraction.box)
        }
        for cursor in cursors.list(f"sync_cursors:{Settings().box_folder_id}"):
            if cursor["retired"]:
                files[cursor["file_id"]] = {**cursor, "name": cursor["file_id"]}
        runs = sorted(cursors.list("sync_runs"), key=lambda r: r["started_at"], reverse=True)[:20]
        return {"files": list(files.values()), "runs": runs}

    services = Services(
        extraction,
        jobs(aws),
        select_models,
        sources,
        ingress,
        training,
        lambda: results.list("eval_reports"),
    )
    return create_app(
        services, security, DynamoThrottle(dynamo.Table(os.environ["KLOOP_WEBHOOK_DEDUPE_TABLE"]))
    )


@lru_cache(maxsize=1)
def worker_runtime():
    aws = session()
    storage = DynamoStorage(aws.resource("dynamodb").Table(os.environ["KLOOP_ITEMS_TABLE"]))
    extraction = LazyService(lambda: plugin(os.environ["KLOOP_EXTRACTION_FACTORY"], aws))

    def documents(sha):
        value = storage.get("approved_snapshots", sha)
        if value is None:
            raise ValueError("Pinned snapshot is missing")
        snapshot = ApprovedSnapshot.model_validate(value)
        from kloop.extract.service import digest

        if (
            snapshot.sha256 != sha
            or digest([i.model_dump(mode="json") for i in snapshot.items]) != sha
        ):
            raise ValueError("Pinned snapshot failed integrity check")
        pairs = sorted({(i.source_file_id, i.source_version_id) for i in snapshot.items})
        documents = [extraction.box.get_document(file, version) for file, version in pairs]
        if [(d.file_id, d.version_id) for d in documents] != pairs:
            raise ValueError("Source version differs from pinned snapshot")
        quotes = {pair: [] for pair in pairs}
        for item in snapshot.items:
            quotes[item.source_file_id, item.source_version_id].append(item.supporting_quote)
        return SearchEvidence(documents, quotes)

    model = ImportedModelClient(
        aws.client(
            "bedrock-runtime",
            config=Config(connect_timeout=5, read_timeout=60, retries={"total_max_attempts": 1}),
        )
    )
    return Worker(jobs(aws), model, documents)
