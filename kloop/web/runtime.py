"""Deployment composition. Imports are credential-free; clients are lazy per Lambda."""

import importlib
import logging
import os
from functools import lru_cache

import boto3
from botocore.config import Config

from kloop.adapters.aws import DynamoStorage, S3Artifacts
from kloop.answer.bedrock import ImportedModelClient
from kloop.answer.corpus import (
    CorpusStore,
    SearchCorpus,
    fetch_documents,
    quotes_for,
    validate_snapshot,
)
from kloop.config import Settings
from kloop.extract.runtime import snapshot_storage
from kloop.web.api import Services, create_app
from kloop.web.jobs import DynamoJobs, JobService, SearchEvidence, SQSDispatch, Worker
from kloop.web.security import DynamoThrottle, Security
from kloop.web.sources import source_activity
from kloop.web.training import training_control
from kloop.web.versions import VersionCatalog

logger = logging.getLogger(__name__)


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


def trained_model(current):
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
    elif os.getenv("KLOOP_TEMPORARY_TRAINED_MODEL_ARN"):
        trained = {
            "arn": os.environ["KLOOP_TEMPORARY_TRAINED_MODEL_ARN"],
            "version_id": "Halvard POC, temporary",
            "snapshot_sha256": None,
        }
    return trained


@lru_cache(maxsize=1)
def api_runtime():
    from kloop.train.state import DynamoTrainingStore, TrainingBusy
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
        base = (
            {
                "arn": os.environ["KLOOP_BASE_MODEL_ID"],
                "version_id": os.getenv("KLOOP_BASE_VERSION_ID", "base"),
                "snapshot_sha256": None,
            }
            if os.getenv("KLOOP_BASE_MODEL_ID")
            else None
        )
        current_id = version_store.current()
        current = version_store.get(current_id) if current_id else None
        trained = trained_model(current)
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
        return source_activity(
            list(files.values()),
            runs,
            dynamo.Table(os.environ["KLOOP_WEBHOOK_DEDUPE_TABLE"]),
            Settings().box_folder_id,
            extraction.reviews(),
        )

    from kloop.train.loading_runtime import service as loading_service

    loading = LazyService(lambda: loading_service(aws))
    catalog = LazyService(
        lambda: VersionCatalog(
            version_store,
            loading,
            S3Artifacts(aws.client("s3"), Settings().artifact_bucket),
            snapshot_storage(aws),
        )
    )
    services = Services(
        extraction,
        jobs(aws),
        select_models,
        sources,
        ingress,
        training,
        lambda: results.list("eval_reports"),
        training_busy=TrainingBusy,
        version_loading=loading,
        model_guard=lambda: loading.guard(),
        version_catalog=catalog,
        training_control=lambda versions, now: training_control(version_store, versions, now),
    )
    return create_app(
        services, security, DynamoThrottle(dynamo.Table(os.environ["KLOOP_WEBHOOK_DEDUPE_TABLE"]))
    )


@lru_cache(maxsize=1)
def worker_runtime():
    aws = session()
    storage = snapshot_storage(aws)
    extraction = LazyService(lambda: plugin(os.environ["KLOOP_EXTRACTION_FACTORY"], aws))

    corpora = CorpusStore(storage.bodies)

    @lru_cache(maxsize=2)
    def cached_documents(sha):
        corpus = corpora.load(sha)
        snapshot = validate_snapshot(storage.get("approved_snapshots", sha), sha)
        expected = SearchCorpus.build(snapshot, corpus.documents)
        if expected != corpus:
            raise ValueError("Search corpus index differs from approved sources")
        pairs = {(i.source_file_id, i.source_version_id) for i in snapshot.items}
        if any((d.file_id, d.version_id) not in pairs for d in corpus.documents):
            raise ValueError("Search corpus contains a source outside the pinned snapshot")
        return SearchEvidence(
            corpus.documents, quotes_for(snapshot, corpus.documents), corpus.index
        )

    def documents(sha):
        try:
            return cached_documents(sha)
        except KeyError as error:
            # Only a missing Search corpus permits live fallback. Snapshot corruption must fail.
            from kloop.answer.corpus import corpus_key

            if error.args != (corpus_key(sha),):
                raise
        snapshot = validate_snapshot(storage.get("approved_snapshots", sha), sha)
        logger.info("Search corpus missing; live source fallback snapshot=%s", sha)
        loaded = fetch_documents(
            snapshot, extraction.box.get_document, lambda file: extraction.retire(file)
        )
        corpus = SearchCorpus.build(snapshot, loaded)
        return SearchEvidence(loaded, quotes_for(snapshot, loaded), corpus.index)

    model = ImportedModelClient(
        aws.client(
            "bedrock-runtime",
            config=Config(connect_timeout=5, read_timeout=60, retries={"total_max_attempts": 1}),
        )
    )
    retriever_mode = os.getenv("SEARCH_RETRIEVER", "box_hybrid")
    if retriever_mode not in {"local", "box_hybrid"}:
        raise ValueError("SEARCH_RETRIEVER must be local or box_hybrid")

    @lru_cache(maxsize=1)
    def box_search():
        from kloop.answer.box_search import BoxSearch

        return BoxSearch(extraction.box.sdk, Settings().box_folder_id)

    return Worker(
        jobs(aws),
        model,
        documents,
        search_retriever=(lambda question, evidence: box_search()(question, evidence))
        if retriever_mode == "box_hybrid"
        else None,
    )
