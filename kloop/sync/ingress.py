"""Signature-only webhook ingress; authenticated API code calls sync_now separately."""

import base64
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from pydantic import Field, ValidationError

from kloop.box.webhooks import verify_webhook
from kloop.schemas import Schema
from kloop.sync.state import SyncState


class Source(Schema):
    id: str = Field(min_length=1)
    type: str


class WebhookEvent(Schema):
    # Box includes additional delivery metadata; only parse the selected fields.
    id: str = Field(min_length=1)
    trigger: str
    source: Source


class SyncIngress:
    def __init__(
        self,
        folder_id: str,
        state: SyncState,
        dispatch: Callable,
        keys: Callable[[], Mapping[str, str]],
        *,
        clock: Callable[[], float] = time.time,
    ):
        self.folder_id, self.state, self.dispatch = folder_id, state, dispatch
        self.keys, self.clock = keys, clock

    def webhook(self, request: dict) -> dict:
        try:
            body = request.get("body", "")
            raw = (
                base64.b64decode(body, validate=True)
                if request.get("isBase64Encoded")
                else (body.encode("utf-8"))
            )
        except (ValueError, TypeError, AttributeError):
            return {"statusCode": 400, "body": "Invalid body"}
        if not verify_webhook(
            raw,
            request.get("headers") or {},
            **self.keys(),
            now=datetime.fromtimestamp(self.clock(), UTC),
        ):
            return {"statusCode": 403, "body": "Invalid signature"}
        try:
            value = json.loads(raw)
            source = value["source"]
            event = WebhookEvent.model_validate(
                {
                    "id": value["id"],
                    "trigger": value["trigger"],
                    "source": {"id": source["id"], "type": source["type"]},
                }
            )
        except (ValueError, TypeError, KeyError, ValidationError):
            return {"statusCode": 400, "body": "Invalid event"}
        if event.trigger not in {"FILE.UPLOADED", "FILE.TRASHED", "FILE.DELETED"} or (
            event.source.type != "file"
        ):
            return {"statusCode": 204, "body": ""}
        # Payload source metadata never drives deletion or extraction. A worker
        # scans the configured folder via CCG, so stale/out-of-scope events are safe.
        if self.state.receive(
            self.folder_id, event.id, int(self.clock()), event_type=event.trigger
        ):
            self.dispatch("webhook", event.id)
        return {"statusCode": 202, "body": "Accepted"}

    def reconcile(self) -> int:
        """Schedule recovers a crash anywhere between receipt and worker completion."""
        pending = self.state.pending(self.folder_id)
        if pending:
            self.dispatch("webhook", None)
        return len(pending)

    def sync_now(self) -> dict:
        """Caller must authenticate the shared-password cookie and enforce CSRF."""
        self.dispatch("manual", None)
        return {"statusCode": 202, "body": "Accepted"}
