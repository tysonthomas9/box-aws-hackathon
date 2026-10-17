import hashlib
import json
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from kloop.adapters.memory import MemoryArtifacts
from kloop.cleanup import CleanupLedger
from kloop.schemas import ModelVersion
from kloop.train.loading import ModelGuard, VersionLoading
from kloop.train.loading_workflow import definition
from kloop.train.state import DynamoTrainingStore, TrainingBusy
from kloop.train.weights import record_weights, verify_weights


@pytest.fixture
def loader(aws_session):
    table = aws_session.resource("dynamodb").create_table(
        TableName="loading",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ("pk", "sk")],
        BillingMode="PAY_PER_REQUEST",
    )
    store = DynamoTrainingStore(table)
    store.save(
        ModelVersion(
            id="candidate",
            status="rejected",
            manifest={"weights": {"s3_uri": "s3://retained/weights/"}},
        )
    )
    slots = Mock()
    slots.models = set()
    slots.census.side_effect = lambda: set(slots.models)
    slots.ledger = CleanupLedger(table, "kloop")
    slots.protected = set()

    def delete(key, **kwargs):
        row = next((r for r in slots.ledger.entries() if r["key"] == key), None)
        if row:
            slots.models.discard(row["resource_id"])
            slots.ledger.remove(row)
        return True

    slots.delete.side_effect = delete
    loading = VersionLoading(
        store,
        slots,
        Mock(),
        ModelGuard(table),
        Mock(),
        clock=lambda: 1000,
        protected=lambda: slots.protected,
        import_role="import-role",
        warm=Mock(),
    )
    return loading


def test_slot_limit_requires_explicit_unload(loader):
    loader.slots.models = {"base", "current", "other"}
    with pytest.raises(ValueError, match="three slots"):
        loader.load("candidate")
    assert loader.store.lock() is None
    loader.slots.delete.assert_not_called()
    loader.dispatch.assert_not_called()


def test_single_shared_training_load_lock(loader):
    loader.load("candidate")
    loader.store.save(ModelVersion(id="second", status="rejected"))
    with pytest.raises(TrainingBusy):
        loader.load("second")
    with pytest.raises(TrainingBusy):
        loader.store.acquire("training", 1000)
    loader.dispatch.assert_called_once()


def loaded(loader, arn="other"):
    version = loader.store.get("candidate")
    version.import_arn = arn
    loader.store.save(version)
    loader.slots.models.add(arn)
    loader.slots.ledger.reserve("import:old", "bedrock_import", "old")
    loader.slots.ledger.resolve("import:old", arn)


@pytest.mark.parametrize("protected", ["base", "promoted", "ask", "eval"])
def test_protected_models_cannot_be_unloaded(loader, protected):
    loaded(loader, protected)
    loader.slots.protected.add(protected)
    with pytest.raises(ValueError, match="active models"):
        loader.unload("candidate")
    loader.slots.delete.assert_not_called()
    assert loader.store.get("candidate").import_arn == protected
    assert loader.store.lock() is None


def test_unload_retains_weights_and_clears_arn_before_delete(loader):
    loaded(loader)
    original = loader.slots.delete.side_effect

    def delete(key, **kwargs):
        assert loader.store.get("candidate").import_arn is None
        return original(key)

    loader.slots.delete.side_effect = delete
    assert loader.unload("candidate")["state"] == "not_loaded"
    assert loader.store.get("candidate").manifest["weights"]["s3_uri"] == "s3://retained/weights/"
    assert loader.catalog()["slots_used"] == 0


def test_unload_races_ask_admission_fail_closed(loader):
    loaded(loader)
    with loader.guard(), pytest.raises(ValueError, match="busy"):
        loader.unload("candidate")
    loader.slots.delete.assert_not_called()
    assert loader.store.lock() is None


def test_asynchronous_delete_is_retriable_and_not_selectable(loader):
    loaded(loader)
    loader.slots.delete.side_effect = None
    loader.slots.delete.return_value = False
    assert loader.unload("candidate")["deleting"]
    assert loader.store.get("candidate").import_arn is None
    assert loader.catalog()["versions"][0]["state"] == "loading"
    loader.slots.delete.return_value = True
    assert loader.unload("candidate")["state"] == "not_loaded"


def test_load_worker_records_new_arn_and_does_not_promote(loader):
    loader.load("candidate")
    owner = loader.store.lock()["owner"]
    loader.step("create", "candidate", owner)
    loader.slots.create.assert_called_once_with(owner, "import-role", "s3://retained/weights/")
    loader.slots.poll.return_value = {"status": "Completed", "importedModelArn": "new-import"}
    loader.step("poll", "candidate", owner)
    assert loader.store.get("candidate").import_arn is None
    loader.step("warm", "candidate", owner)
    assert loader.store.get("candidate").import_arn == "new-import"
    assert loader.store.get("candidate").status == "rejected"
    assert loader.store.current() is None
    loader.step("finish", "candidate", owner)
    assert loader.store.lock() is None


def test_readiness_reimport_only_once(loader):
    loader.load("candidate")
    owner = loader.store.lock()["owner"]
    loader.step("create", "candidate", owner)
    assert loader.step("reimport", "candidate", owner)["complete"]
    loader.step("create", "candidate", owner)
    assert loader.slots.create.call_args.args[0] == owner + "-r1"
    with pytest.raises(ValueError, match="already attempted"):
        loader.step("reimport", "candidate", owner)


def test_cleanup_waits_for_admitted_worker_and_retains_lock(loader):
    loader.load("candidate")
    owner = loader.store.lock()["owner"]
    loader.store.begin_invocation(owner, "late", 1000)
    assert not loader.step("fail", "candidate", owner)["complete"]
    assert loader.store.lock()["owner"] == owner
    loader.store.end_invocation(owner, "late")
    assert loader.step("fail", "candidate", owner)["complete"]
    assert loader.store.lock() is None


def report():
    files = {
        f"training/candidate/merged/{name}": {
            "bytes": 1,
            "sha256": hashlib.sha256(b"x").hexdigest(),
        }
        for name in ("config.json", "tokenizer_config.json", "model.safetensors")
    }
    return json.dumps(
        {"merged_s3_uri": "s3://retained/training/candidate/merged/", "files": files}
    ).encode()


def test_weight_inventory_is_pinned_and_verified():
    artifacts = MemoryArtifacts()
    artifacts.put("training/candidate/report.json", report(), "application/json")
    version = ModelVersion(id="candidate")
    value = record_weights(version, artifacts, "retained")
    assert value["report_sha256"] == hashlib.sha256(report()).hexdigest()
    s3 = Mock()
    body = Mock()
    body.iter_chunks.return_value = [b"bad"]
    s3.get_object.return_value = {"Body": nullcontext(body)}
    # Report reads and streamed object reads use separate injected paths.
    from unittest.mock import patch

    with (
        patch("kloop.adapters.aws.S3Artifacts", return_value=artifacts),
        pytest.raises(ValueError, match="integrity"),
    ):
        verify_weights(version, s3, "retained")


def test_workflow_is_bounded_and_matches_generated_file():
    from pathlib import Path

    flow = definition("${worker_arn}")
    assert flow["TimeoutSeconds"] == 7200
    assert json.loads(Path("infra/loading.asl.json").read_text()) == flow
    assert flow["States"]["Work"]["Branches"][0]["States"]["Warm"]["Catch"][0]["ErrorEquals"] == [
        "ModelWarming"
    ]


def test_iam_restricts_delete_and_passrole():
    from pathlib import Path

    policy = Path("infra/loading.tf").read_text()
    assert '"aws:ResourceTag/deployment" = local.prefix' in policy
    assert '"aws:RequestTag/deployment" = local.prefix' in policy
    assert 'Resource = aws_iam_role.training["bedrock"].arn' in policy
    assert '"iam:PassedToService" = "bedrock.amazonaws.com"' in policy
    assert '"us-east-1"' not in policy


def test_load_resume_reuses_same_execution_after_lost_reply(loader):
    loader.load("candidate")
    owner = loader.store.lock()["owner"]
    assert loader.load("candidate")["state"] == "loading"
    assert loader.dispatch.call_args.args == ("candidate", owner)
    assert len(loader.slots.ledger.entries()) == 0


def test_evaluation_pin_blocks_unload_and_cleans_up(loader, aws_session, monkeypatch):
    from kloop.train.model_activity import evaluation_pin

    monkeypatch.setenv("KLOOP_VERSIONS_TABLE", loader.store.table.name)
    with evaluation_pin(aws_session, {"candidate_arn": "candidate-arn"}):
        rows = loader.store.storage.list("model_activity")
        assert rows[0]["arns"] == ["candidate-arn"]
        assert rows[0]["until"] > 0
    assert loader.store.storage.list("model_activity") == []


@pytest.mark.parametrize("action", ["load", "unload"])
def test_version_mutations_require_signin_and_csrf(loader, action):
    from fastapi.testclient import TestClient

    from kloop.web.api import Services, create_app
    from kloop.web.security import COOKIE, MemoryThrottle, Security

    origin = "https://app.example"
    security = Security("password", "s" * 48, "o" * 48, origin)
    service = Services(
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        training_busy=TrainingBusy,
        version_loading=loader,
    )
    client = TestClient(
        create_app(service, security, MemoryThrottle(), clock=lambda: 1000), base_url=origin
    )
    path = f"/api/versions/candidate/{action}"
    headers = {"x-kloop-origin": "o" * 48, "origin": origin}
    assert client.post(path, headers=headers).status_code == 401
    token, csrf = security.issue(1000)
    client.cookies.set(COOKIE, token)
    assert client.post(path, headers=headers).status_code == 403
    headers["x-csrf-token"] = csrf
    response = client.post(path, headers=headers)
    assert response.status_code == (202 if action == "load" else 200)


def test_definitively_rejected_dispatch_releases_lock(loader):
    from kloop.train.service import DispatchRejected

    loader.dispatch.side_effect = DispatchRejected("refused")
    with pytest.raises(ValueError, match="workflow was refused"):
        loader.load("candidate")
    assert loader.store.lock() is None
    assert loader.store.get("candidate").manifest["loading"]["state"] == "failed"


def test_uncertain_dispatch_keeps_lock_for_safe_resume(loader):
    loader.dispatch.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        loader.load("candidate")
    assert loader.store.lock() is not None
    loader.dispatch.side_effect = None
    assert loader.load("candidate")["state"] == "loading"


def test_production_protection_reads_evaluation_pins(loader, aws_session, monkeypatch):
    from kloop.train.loading_runtime import service
    from kloop.train.model_activity import evaluation_pin

    for key in ("VERSIONS_TABLE", "ASK_JOBS_TABLE", "CLEANUP_LEDGER_TABLE"):
        monkeypatch.setenv("KLOOP_" + key, loader.store.table.name)
    monkeypatch.setenv("KLOOP_TRAIN_DEPLOYMENT", "kloop")
    monkeypatch.setenv("KLOOP_ARTIFACT_BUCKET", "retained")
    monkeypatch.setenv("KLOOP_IMPORT_ROLE", "import-role")
    actual = service(aws_session)
    loaded(loader, "eval-arn")
    with evaluation_pin(aws_session, {"candidate_arn": "eval-arn"}):
        with pytest.raises(ValueError, match="active models"):
            actual.unload("candidate")
    assert actual.store.get("candidate").import_arn == "eval-arn"


def test_temporary_catalog_model_requires_live_presence_and_is_protected(loader):
    loader.temporary = {"id": "Halvard POC, temporary", "arn": "temporary"}
    assert len(loader.catalog()["versions"]) == 1
    loader.slots.models.add("temporary")
    row = loader.catalog()["versions"][-1]
    assert row["id"] == "Halvard POC, temporary"
    assert row["state"] == "loaded"
    assert not row["can_load"] and not row["can_unload"]


@pytest.mark.parametrize("action", ["reimport", "fail"])
def test_worker_cleanup_serializes_with_reader_admission(loader, action):
    loader.load("candidate")
    owner = loader.store.lock()["owner"]
    loader.step("create", "candidate", owner)
    with loader.guard(), pytest.raises(ValueError, match="busy"):
        loader.step(action, "candidate", owner)
    loader.slots.delete.assert_not_called()
    assert loader.store.lock()["owner"] == owner


def test_explicit_unload_protects_active_evaluation_not_old_report_retention(
    loader, aws_session, monkeypatch
):
    from kloop.train.loading_runtime import service

    for key in ("VERSIONS_TABLE", "ASK_JOBS_TABLE", "CLEANUP_LEDGER_TABLE"):
        monkeypatch.setenv("KLOOP_" + key, loader.store.table.name)
    monkeypatch.setenv("KLOOP_TRAIN_DEPLOYMENT", "kloop")
    monkeypatch.setenv("KLOOP_ARTIFACT_BUCKET", "retained")
    monkeypatch.setenv("KLOOP_IMPORT_ROLE", "import-role")
    version = loader.store.get("candidate")
    version.import_arn = "medical-arn"
    version.manifest["retain_for_medical_report"] = True
    loader.store.save(version)
    actual = service(aws_session)
    assert "medical-arn" not in actual.protected()
    version.status = "evaluating"
    loader.store.save(version)
    assert "medical-arn" in actual.protected()


@pytest.mark.parametrize("label", [None, "Medical preview, temporary"])
def test_temporary_catalog_label_matches_serving_label(loader, aws_session, monkeypatch, label):
    from kloop.train.loading_runtime import service
    from kloop.web.runtime import trained_model

    for key in ("VERSIONS_TABLE", "ASK_JOBS_TABLE", "CLEANUP_LEDGER_TABLE"):
        monkeypatch.setenv("KLOOP_" + key, loader.store.table.name)
    monkeypatch.setenv("KLOOP_TRAIN_DEPLOYMENT", "kloop")
    monkeypatch.setenv("KLOOP_ARTIFACT_BUCKET", "retained")
    monkeypatch.setenv("KLOOP_IMPORT_ROLE", "import-role")
    monkeypatch.setenv("KLOOP_TEMPORARY_TRAINED_MODEL_ARN", "temporary")
    if label is None:
        monkeypatch.delenv("KLOOP_TEMPORARY_TRAINED_MODEL_LABEL", raising=False)
    else:
        monkeypatch.setenv("KLOOP_TEMPORARY_TRAINED_MODEL_LABEL", label)
    actual = service(aws_session)
    actual.slots.census = lambda: {"temporary"}
    row = actual.catalog()["versions"][-1]
    assert row["id"] == trained_model(None)["version_id"]
    assert row["id"] == (label if label is not None else "Halvard POC, temporary")
    assert not row["can_load"] and not row["can_unload"]
