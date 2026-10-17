"""Sync plugin: KLOOP_EXTRACTION_FACTORY=kloop.extract.runtime:factory.

Uses the existing CCG secret, row-based knowledge in the items table and immutable
snapshot bodies in the artifact bucket. Clients are constructed only at runtime.
"""

import os

from botocore.config import Config

from kloop.adapters.aws import DynamoStorage
from kloop.answer.corpus import CorpusStore
from kloop.box.auth import token_provider
from kloop.box.client import BoxClient, sdk_client
from kloop.config import Settings
from kloop.extract.provider import BoxAIExtractor, GLMExtractor
from kloop.extract.repository import DynamoRepository
from kloop.extract.service import ExtractionService
from kloop.extract.snapshots import S3SnapshotBodies, SnapshotStorage


def factory(session) -> ExtractionService:
    settings = Settings()
    sdk = sdk_client(token_provider(session.client("secretsmanager"), settings, mode="ccg"))
    box = BoxClient(sdk, settings.box_folder_id)
    runtime = session.client(
        "bedrock-runtime",
        config=Config(
            connect_timeout=5,
            read_timeout=120,
            retries={"total_max_attempts": 3, "mode": "adaptive"},
        ),
    )
    table = session.resource("dynamodb").Table(os.getenv("KLOOP_ITEMS_TABLE", settings.table_name))
    bodies = S3SnapshotBodies(session.client("s3"), settings.artifact_bucket)
    return ExtractionService(
        box,
        BoxAIExtractor(sdk, GLMExtractor(runtime)),
        DynamoRepository(table, bodies),
        os.getenv("KLOOP_REVIEW_MODE", "exceptions"),
        search_corpus=CorpusStore(bodies),
    )


def snapshot_storage(session) -> SnapshotStorage:
    """Read immutable snapshots by hash without creating Box/model clients."""
    settings = Settings()
    table = session.resource("dynamodb").Table(os.getenv("KLOOP_ITEMS_TABLE", settings.table_name))
    return SnapshotStorage(
        DynamoStorage(table), S3SnapshotBodies(session.client("s3"), settings.artifact_bucket)
    )
