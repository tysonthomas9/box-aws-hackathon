"""Sync plugin: KLOOP_EXTRACTION_FACTORY=kloop.extract.runtime:factory.

Uses the existing service-account CCG secret and the items table. Knowledge and
review decisions share an atomic bounded record; approved_snapshots are separate
immutable records in that table. No credentials or clients are loaded at import.
"""

import os

from botocore.config import Config

from kloop.box.auth import token_provider
from kloop.box.client import BoxClient, sdk_client
from kloop.config import Settings
from kloop.extract.provider import BoxAIExtractor, GLMExtractor
from kloop.extract.repository import DynamoRepository
from kloop.extract.service import ExtractionService


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
    return ExtractionService(
        box,
        BoxAIExtractor(sdk, GLMExtractor(runtime)),
        DynamoRepository(table),
        os.getenv("KLOOP_REVIEW_MODE", "exceptions"),
    )
