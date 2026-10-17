import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kloop.adapters.memory import MemoryStorage
from kloop.box.client import BoxClient
from kloop.sync.ingress import SyncIngress
from kloop.sync.service import SyncService, source_files
from kloop.sync.state import LambdaDispatch, SyncState
from kloop.sync.subscription import seed_webhook

NOW = datetime(2026, 10, 17, 7, tzinfo=UTC)


def file(id="f", version="v1"):
    return SimpleNamespace(
        type="file", id=id, file_version=SimpleNamespace(id=version), name=id + ".txt", etag="e"
    )


def folder(id, name):
    return SimpleNamespace(type="folder", id=id, name=name)


@pytest.fixture
def state(aws_session):
    db = aws_session.resource("dynamodb")
    tables = []
    for name in ("receipts", "cursors"):
        tables.append(
            db.create_table(
                TableName=name,
                KeySchema=[
                    {"AttributeName": "pk", "KeyType": "HASH"},
                    {"AttributeName": "sk", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": k, "AttributeType": "S"} for k in ("pk", "sk")
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        )
    return SyncState(*tables)


@pytest.fixture
def setup(state):
    box = Mock(spec=BoxClient)
    box.folder_id = "halvard"
    box._info = BoxClient._info
    box.list_folder.return_value = [file()]
    extraction = Mock()
    extraction.process.return_value = 1
    extraction.retire.return_value = 1
    storage = MemoryStorage()
    service = SyncService(box, extraction, storage, state, clock=lambda: NOW.timestamp())
    return box, extraction, storage, service


def request(event_id="body-event", trigger="FILE.UPLOADED"):
    raw = json.dumps(
        {
            "id": event_id,
            "trigger": trigger,
            "source": {"id": "f", "type": "file", "name": "extra"},
            "created_at": "extra",
        }
    ).encode()
    timestamp = NOW.isoformat()
    signature = base64.b64encode(hmac.digest(b"key", raw + timestamp.encode(), hashlib.sha256))
    return {
        "body": raw.decode(),
        "headers": {
            "Box-Delivery-Timestamp": timestamp,
            "Box-Signature-Primary": signature.decode(),
            "Box-Delivery-Id": "delivery-does-not-dedupe",
        },
    }


def ingress(state, dispatch):
    return SyncIngress(
        "halvard", state, dispatch, lambda: {"primary_key": "key"}, clock=lambda: NOW.timestamp()
    )


def test_duplicate_body_event_is_enqueued_once(state, setup):
    dispatch = Mock()
    api = ingress(state, dispatch)
    assert api.webhook(request())["statusCode"] == 202
    second = request()
    second["headers"]["Box-Delivery-Id"] = "different-delivery"
    assert api.webhook(second)["statusCode"] == 202
    dispatch.assert_called_once_with("webhook", "body-event")
    setup[3].run("webhook", "body-event")
    setup[3].run("webhook", "body-event")
    setup[1].process.assert_called_once_with("f", "v1")
    assert state.pending("halvard") == []
    receipt = state.receipts.get_item(Key={"pk": "receipts:halvard", "sk": "body-event"})["Item"]
    assert receipt["expires_at"] == int(NOW.timestamp()) + 7 * 86400


def test_bad_signature_has_no_side_effects(state):
    dispatch = Mock()
    req = request()
    req["body"] += " "
    assert ingress(state, dispatch).webhook(req)["statusCode"] == 403
    assert state.pending("halvard") == []
    dispatch.assert_not_called()


@pytest.mark.parametrize("trigger", ["FILE.TRASHED", "FILE.DELETED"])
def test_deleted_file_retires_once(state, setup, trigger):
    box, extraction, storage, service = setup
    service.run("manual")
    box.list_folder.return_value = []
    assert ingress(state, Mock()).webhook(request(trigger=trigger))["statusCode"] == 202
    assert service.run("webhook")["changes"] == 1
    assert service.run("schedule")["changes"] == 0
    extraction.retire.assert_called_once_with("f")
    assert storage.get("sync_cursors:halvard", "f")["retired"] is True


def test_unchanged_and_rejected_review_are_untouched(setup):
    _, extraction, storage, service = setup
    service.run("manual")
    storage.put("reviews", "rejected", {"decision": "rejected"})
    before = storage.get("reviews", "rejected")
    result = service.run("schedule")
    assert result["changes"] == 0
    assert storage.get("reviews", "rejected") == before
    extraction.process.assert_called_once()


def test_new_version_only_checkpoints_after_durable_extraction(setup):
    box, extraction, storage, service = setup
    service.run("manual")
    box.list_folder.return_value = [file(version="v2")]
    extraction.process.side_effect = RuntimeError("sensitive SDK response")
    with pytest.raises(RuntimeError):
        service.run("schedule")
    assert storage.get("sync_cursors:halvard", "f")["version_id"] == "v1"
    failed = [r for r in storage.list("sync_runs") if r["status"] == "failed"]
    assert failed[0]["error_type"] == "RuntimeError"
    assert "sensitive" not in json.dumps(failed)
    extraction.process.side_effect = None
    service.run("schedule")
    assert storage.get("sync_cursors:halvard", "f")["version_id"] == "v2"


def test_pending_receipt_survives_crash_before_dispatch_and_reconciles(state, setup):
    dispatch = Mock(side_effect=RuntimeError("crash"))
    api = ingress(state, dispatch)
    with pytest.raises(RuntimeError):
        api.webhook(request())
    assert state.pending("halvard") == ["body-event"]
    record = state.receipts.get_item(Key={"pk": "receipts:halvard", "sk": "body-event"})["Item"]
    assert "expires_at" not in record
    dispatch.side_effect = None
    assert api.reconcile() == 1
    setup[3].run("schedule")
    assert state.pending("halvard") == []


def test_failed_extraction_keeps_receipt_pending(state, setup):
    ingress(state, Mock()).webhook(request())
    setup[1].process.side_effect = RuntimeError()
    with pytest.raises(RuntimeError):
        setup[3].run("webhook")
    assert state.pending("halvard") == ["body-event"]
    # Failed worker releases its lock for the scheduled retry.
    setup[1].process.side_effect = None
    assert setup[3].run("schedule")["status"] == "completed"


def test_overlapping_runs_keep_work_pending(state, setup):
    ingress(state, Mock()).webhook(request())
    assert state.acquire("halvard", "other", int(NOW.timestamp()))
    assert setup[3].run("webhook")["status"] == "busy"
    setup[1].process.assert_not_called()
    assert state.pending("halvard") == ["body-event"]
    state.release("halvard", "wrong-owner")
    assert not state.acquire("halvard", "new", int(NOW.timestamp()))
    state.release("halvard", "other")
    assert setup[3].run("schedule")["status"] == "completed"


def test_expired_lock_is_recoverable(state):
    assert state.acquire("halvard", "dead", 1)
    assert state.acquire("halvard", "successor", 962)
    state.release("halvard", "dead")
    assert not state.acquire("halvard", "intruder", 963)


def test_full_recursive_listing_excludes_reports(setup):
    box, extraction, _, service = setup
    box.list_folder.side_effect = lambda id: {
        "halvard": [file(), folder("reports", "reports"), folder("sources", "docs")],
        "sources": [file("nested")],
    }[id]
    assert service.run("schedule")["files_seen"] == 2
    assert extraction.process.call_count == 2
    assert all(call.args[0] != "reports" for call in box.list_folder.call_args_list)


def test_partial_listing_never_infers_deletion_or_processes(setup):
    box, extraction, storage, service = setup
    service.run("manual")
    box.list_folder.side_effect = lambda id: (
        [file("new"), folder("broken", "docs")]
        if id == "halvard"
        else (_ for _ in ()).throw(RuntimeError("partial page"))
    )
    with pytest.raises(RuntimeError):
        service.run("schedule")
    extraction.retire.assert_not_called()
    extraction.process.assert_called_once()
    assert not storage.get("sync_cursors:halvard", "f")["retired"]


def test_real_box_pagination_failure_does_not_return_partial_tree():
    sdk = Mock()
    sdk.folders.get_folder_items.side_effect = [
        SimpleNamespace(entries=[file()], next_marker="second"),
        RuntimeError("Box failed"),
    ]
    with pytest.raises(RuntimeError):
        source_files(BoxClient(sdk, "halvard"))
    assert sdk.folders.get_folder_items.call_args.kwargs["marker"] == "second"


def test_receipt_arriving_during_listing_stays_pending(state, setup):
    box, _, _, service = setup

    def listing(_):
        state.receive("halvard", "late", int(NOW.timestamp()))
        return [file()]

    box.list_folder.side_effect = listing
    service.run("schedule")
    assert state.pending("halvard") == ["late"]


def test_manual_and_async_dispatch(state):
    client = Mock()
    client.invoke.return_value = {"StatusCode": 202}
    dispatch = LambdaDispatch(client, "owned-sync")
    assert ingress(state, dispatch).sync_now()["statusCode"] == 202
    args = client.invoke.call_args.kwargs
    assert args["InvocationType"] == "Event"
    assert json.loads(args["Payload"]) == {"source": "manual", "event_id": None}
    client.invoke.return_value = {"StatusCode": 200}
    with pytest.raises(RuntimeError):
        dispatch("manual")


def test_webhook_seed_resolves_only_as_final_step():
    order = []
    ledger = Mock()
    ledger.entries.return_value = []
    ledger.reserve.side_effect = lambda *a: order.append("reserve")
    ledger.resolve.side_effect = lambda *a: order.append("resolve")
    box = Mock()
    box.folder_id = "halvard"
    box.create_webhook.side_effect = lambda *a: order.append("create") or "hook"
    box.sdk.webhooks.get_webhook_by_id.side_effect = lambda *a: (
        order.append("verify")
        or SimpleNamespace(
            target=SimpleNamespace(id="halvard", type="folder"),
            triggers=["FILE.UPLOADED", "FILE.TRASHED", "FILE.DELETED"],
            address="https://example.test/api/box-webhook",
        )
    )
    assert seed_webhook(box, ledger, "https://example.test/api/box-webhook") == "hook"
    assert order == ["reserve", "create", "verify", "resolve"]
    box.create_webhook.side_effect = RuntimeError("uncertain create")
    ledger.resolve.reset_mock()
    with pytest.raises(RuntimeError):
        seed_webhook(box, ledger, "https://example.test/api/box-webhook")
    ledger.resolve.assert_not_called()


def test_signed_base64_and_missing_keys(state):
    req = request()
    req["body"] = base64.b64encode(req["body"].encode()).decode()
    req["isBase64Encoded"] = True
    assert ingress(state, Mock()).webhook(req)["statusCode"] == 202
    api = SyncIngress("halvard", state, Mock(), lambda: {}, clock=lambda: NOW.timestamp())
    assert api.webhook(request("missing-keys"))["statusCode"] == 403
    assert state.pending("halvard") == ["body-event"]


def test_full_pagination_finishes_before_processing():
    sdk = Mock()
    sdk.folders.get_folder_items.side_effect = [
        SimpleNamespace(entries=[file("first")], next_marker="page2"),
        SimpleNamespace(entries=[file("last")], next_marker=None),
    ]
    assert [f.file_id for f in source_files(BoxClient(sdk, "halvard"))] == ["first", "last"]


def test_failed_retirement_retries_without_checkpoint(setup):
    box, extraction, storage, service = setup
    service.run("manual")
    box.list_folder.return_value = []
    extraction.retire.side_effect = RuntimeError()
    with pytest.raises(RuntimeError):
        service.run("schedule")
    assert not storage.get("sync_cursors:halvard", "f")["retired"]
    extraction.retire.side_effect = None
    service.run("schedule")
    assert storage.get("sync_cursors:halvard", "f")["retired"]
    # A restored file at the same version is extracted again.
    box.list_folder.return_value = [file()]
    service.run("schedule")
    assert not storage.get("sync_cursors:halvard", "f")["retired"]
    assert extraction.process.call_count == 2


def test_webhook_seed_pending_reservation_is_not_recreated():
    ledger, box = Mock(), Mock()
    box.folder_id = "halvard"
    ledger.entries.return_value = [{"key": "box-webhook:halvard", "resource_id": None}]
    with pytest.raises(RuntimeError, match="Reconcile"):
        seed_webhook(box, ledger, "https://example.test")
    box.create_webhook.assert_not_called()


def test_webhook_seed_readback_failure_leaves_pending():
    ledger, box = Mock(), Mock()
    box.folder_id = "halvard"
    ledger.entries.return_value = []
    box.sdk.webhooks.get_webhook_by_id.side_effect = RuntimeError()
    with pytest.raises(RuntimeError):
        seed_webhook(box, ledger, "https://example.test")
    ledger.reserve.assert_called_once()
    ledger.resolve.assert_not_called()


def test_webhook_seed_existing_subscription_is_reused():
    ledger, box = Mock(), Mock()
    box.folder_id = "halvard"
    ledger.entries.return_value = [{"key": "box-webhook:halvard", "resource_id": "owned"}]
    box.sdk.webhooks.get_webhook_by_id.return_value = SimpleNamespace(
        target=SimpleNamespace(id="halvard", type="folder"),
        address="https://example.test",
        triggers=["FILE.UPLOADED", "FILE.TRASHED", "FILE.DELETED"],
    )
    assert seed_webhook(box, ledger, "https://example.test") == "owned"
    ledger.reserve.assert_not_called()
    box.create_webhook.assert_not_called()


def test_lambda_schedule_manual_and_webhook_share_worker(monkeypatch, setup):
    from lambdas import sync

    monkeypatch.setattr(sync, "runtime", lambda: SimpleNamespace(service=setup[3]))
    for source in ("schedule", "manual", "webhook"):
        assert sync.handler({"source": source}, None)["status"] == "completed"
    with pytest.raises(ValueError):
        sync.handler({"source": "untrusted"}, None)
    setup[1].process.assert_called_once()


def test_ingress_runtime_does_not_require_extraction_or_ccg(monkeypatch, aws_session):
    from lambdas.sync import compose_ingress

    monkeypatch.delenv("KLOOP_EXTRACTION_FACTORY", raising=False)
    monkeypatch.setenv("KLOOP_BOX_FOLDER_ID", "halvard")
    monkeypatch.setenv("KLOOP_SYNC_CURSORS_TABLE", "cursors")
    monkeypatch.setenv("KLOOP_WEBHOOK_DEDUPE_TABLE", "receipts")
    monkeypatch.setenv("KLOOP_SYNC_FUNCTION_NAME", "owned-sync")
    api = compose_ingress(aws_session)
    assert api.folder_id == "halvard"


def test_sync_runtime_requires_real_extraction_factory(monkeypatch):
    from lambdas.sync import runtime

    runtime.cache_clear()
    monkeypatch.delenv("KLOOP_EXTRACTION_FACTORY", raising=False)
    monkeypatch.setenv("AWS_PROFILE", "unavailable-profile")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    with pytest.raises(RuntimeError, match="KLOOP_EXTRACTION_FACTORY"):
        runtime()


def test_realistic_fake_survives_cursor_write_failure(setup, monkeypatch):
    from kloop.sync.testing import FakeExtraction

    _, _, storage, service = setup
    fake = FakeExtraction()
    service.extraction = fake
    original_put = storage.put

    def fail_cursor(collection, id, value):
        if collection.startswith("sync_cursors:"):
            raise RuntimeError("crash after durable extraction")
        original_put(collection, id, value)

    monkeypatch.setattr(storage, "put", fail_cursor)
    with pytest.raises(RuntimeError):
        service.run("manual")
    assert fake.versions == {"f": "v1"}
    assert storage.get("sync_cursors:halvard", "f") is None
    monkeypatch.setattr(storage, "put", original_put)
    assert service.run("schedule")["changes"] == 0
    assert storage.get("sync_cursors:halvard", "f")["version_id"] == "v1"
    assert fake.calls == [("process", "f", "v1"), ("process", "f", "v1")]
    assert fake.retire("f") == 1
    assert fake.retire("f") == 0
