"""Runtime composition for sync; extraction factory is wired by the deploy wave.

KLOOP_EXTRACTION_FACTORY must name module:function. The function takes a boto3
Session and returns kloop.sync.ports.Extraction. No fake or no-op fallback is
permitted. API code uses ingress_runtime().webhook / sync_now after route checks;
ingress never constructs or invokes extraction.
"""

import importlib
import os
from dataclasses import dataclass
from functools import lru_cache

import boto3
from botocore.config import Config

from kloop.adapters.aws import DynamoStorage
from kloop.box.auth import token_provider, webhook_keys
from kloop.box.client import BoxClient, sdk_client
from kloop.config import Settings
from kloop.sync.ingress import SyncIngress
from kloop.sync.ports import Extraction
from kloop.sync.service import SyncService
from kloop.sync.state import LambdaDispatch, SyncState


@dataclass
class Runtime:
    ingress: SyncIngress
    service: SyncService


def compose_ingress(session) -> SyncIngress:
    settings = Settings()
    dynamo = session.resource("dynamodb")
    table = dynamo.Table(os.environ["KLOOP_SYNC_CURSORS_TABLE"])
    state = SyncState(dynamo.Table(os.environ["KLOOP_WEBHOOK_DEDUPE_TABLE"]), table)
    secrets = session.client("secretsmanager")
    dispatch = LambdaDispatch(
        session.client(
            "lambda",
            config=Config(
                connect_timeout=2,
                read_timeout=2,
                retries={"total_max_attempts": 1},
            ),
        ),
        os.environ["KLOOP_SYNC_FUNCTION_NAME"],
    )
    if not settings.box_folder_id or settings.box_folder_id == "0":
        raise ValueError("Configure a non-root Halvard folder")
    return SyncIngress(
        settings.box_folder_id,
        state,
        dispatch,
        lambda: webhook_keys(secrets, settings),
    )


def compose(session, extraction: Extraction) -> Runtime:
    settings = Settings()
    ingress = compose_ingress(session)
    box = BoxClient(
        sdk_client(token_provider(session.client("secretsmanager"), settings)),
        settings.box_folder_id,
    )
    table = session.resource("dynamodb").Table(os.environ["KLOOP_SYNC_CURSORS_TABLE"])
    return Runtime(ingress, SyncService(box, extraction, DynamoStorage(table), ingress.state))


@lru_cache(maxsize=1)
def ingress_runtime() -> SyncIngress:
    return compose_ingress(boto3.Session(region_name=Settings().region))


@lru_cache(maxsize=1)
def runtime() -> Runtime:
    settings = Settings()
    session = boto3.Session(region_name=settings.region)
    path = os.environ.get("KLOOP_EXTRACTION_FACTORY", "")
    if ":" not in path:
        raise RuntimeError("Deploy must configure KLOOP_EXTRACTION_FACTORY=module:function")
    module, function = path.split(":", 1)
    extraction = getattr(importlib.import_module(module), function)(session)
    return compose(session, extraction)


def handler(event, context):
    """Only trusted Lambda invokers call this worker; HTTP routes use ingress."""
    app = runtime()
    trigger = event.get("source")
    if trigger == "schedule":
        # No separate dispatch needed: this invocation reconciles all receipts.
        return app.service.run("schedule")
    if trigger in {"webhook", "manual"}:
        return app.service.run(trigger, event.get("event_id"))
    raise ValueError("Unknown sync event")
