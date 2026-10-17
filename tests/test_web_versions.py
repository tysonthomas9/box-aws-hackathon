"""The training browser follows immutable training bindings and never reads eval sets."""

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kloop.extract.hashing import digest
from kloop.schemas import ApprovedSnapshot, Item, ModelVersion
from kloop.train.data import encoded
from kloop.web.versions import VersionCatalog


@pytest.fixture
def catalog():
    item = Item(
        id="item",
        attribute_id="a",
        kind="fact",
        subject="Policy",
        statement="Approved value",
        supporting_quote="Approved value",
        source_file_id="42",
        source_version_id="7",
        extractor="test",
        status="approved",
    )
    snapshot = ApprovedSnapshot(sha256=digest([item.model_dump(mode="json")]), items=[item])
    rows = [
        {
            "question": f"Training question {i}?",
            "answer": f"Approved answer {i}.",
            "kind": "fact" if i < 28 else "replay",
            "source_item_ids": ["item"] if i < 28 else [],
        }
        for i in range(30)
    ]
    train = b"".join(
        encoded(
            {
                "messages": [
                    {"role": "system", "content": "Training"},
                    {"role": "user", "content": r["question"]},
                    {"role": "assistant", "content": r["answer"]},
                ]
            }
        )
        + b"\n"
        for r in rows
    )
    manifest = {
        "snapshot_hash": snapshot.sha256,
        "rows": 30,
        "counts": {"fact": 28, "replay": 2},
        "train_sha256": hashlib.sha256(train).hexdigest(),
        "lineage": rows,
        "partial_training_deviation": {"near_miss_omitted": True},
        "uncovered_item_ids": [],
    }
    body = encoded(manifest)
    sha = hashlib.sha256(body).hexdigest()
    prefix = "training/data/" + sha
    version = ModelVersion(
        id="v2",
        status="rejected",
        import_arn="arn:v2",
        manifest={
            "snapshot_hash": snapshot.sha256,
            "manifest_hash": sha,
            "data_prefix": prefix,
            "created_at": 100,
            "evaluation": {"counts": {"candidate": {"correct": 2, "total": 4}}},
            "pretraining_audit": {"sha256": "b" * 64},
        },
    )
    store = Mock()
    store.versions.return_value = [version]
    store.get.side_effect = lambda id: version if id == "v2" else None
    store.current.return_value = "v2"
    loading = Mock()
    loading.catalog.return_value = {
        "versions": [
            {
                "id": "v2",
                "state": "loaded",
                "import_arn": "arn:v2",
                "can_load": False,
                "can_unload": False,
            },
            {
                "id": "temporary",
                "state": "loaded",
                "import_arn": "arn:temporary",
                "can_load": False,
                "can_unload": False,
            },
        ],
        "load_active": False,
        "slots_used": 2,
        "slot_limit": 3,
    }
    objects = {f"{prefix}/manifest.json": body, f"{prefix}/train.jsonl": train}
    artifacts = Mock()
    artifacts.get.side_effect = lambda key: objects[key]
    snapshots = Mock()
    snapshots.get.return_value = snapshot.model_dump(mode="json")
    service = VersionCatalog(store, loading, artifacts, snapshots)
    return SimpleNamespace(
        service=service,
        version=version,
        store=store,
        loading=loading,
        objects=objects,
        artifacts=artifacts,
        snapshots=snapshots,
        prefix=prefix,
    )


def test_catalog_defaults_to_current_then_temporary_and_never_mutates_pointer(catalog):
    value = catalog.service.list()
    assert value["default_version_id"] == "v2"
    assert value["versions"][0]["training_data_available"] is True
    assert value["versions"][0]["dev_score"] == {"candidate": {"correct": 2, "total": 4}}
    assert catalog.service.resolve("v2")["version_id"] == "v2"
    catalog.loading.catalog.return_value["versions"][0]["state"] = "not_loaded"
    assert catalog.service.list()["default_version_id"] == "temporary"
    with pytest.raises(ValueError, match="loaded"):
        catalog.service.resolve("v2")
    with pytest.raises(ValueError):
        catalog.service.resolve("arn:arbitrary")
    assert catalog.store.method_calls == [
        call for call in catalog.store.method_calls if call[0] in {"versions", "current", "get"}
    ]


def test_training_rows_search_paginate_join_exact_source_and_expose_only_hashes(catalog):
    first = catalog.service.training_rows("v2")
    assert len(first["rows"]) == 25
    assert first["rows"][0]["sources"] == [{"file_id": "42", "version_id": "7"}]
    assert first["counts"] == {"fact": 28, "replay": 2}
    assert first["audit_sha256"] == "b" * 64
    second = catalog.service.training_rows("v2", page=2)
    assert len(second["rows"]) == 5 and second["rows"][0]["index"] == 26
    assert catalog.service.training_rows("v2", q="answer 29")["total"] == 1
    assert catalog.service.training_rows("v2", kind="replay")["total"] == 2
    assert catalog.service.training_rows("v2", q="no matching content")["rows"] == []
    assert catalog.service.training_rows("v2", page=100)["rows"] == []
    assert {call.args[0] for call in catalog.artifacts.get.call_args_list} == {
        catalog.prefix + "/manifest.json",
        catalog.prefix + "/train.jsonl",
    }
    assert all(
        call.args == ("approved_snapshots", catalog.version.manifest["snapshot_hash"])
        for call in catalog.snapshots.get.call_args_list
    )


@pytest.mark.parametrize(
    "kwargs", [{"kind": "hidden"}, {"kind": "dev"}, {"page": 0}, {"q": "a" * 201}]
)
def test_viewer_rejects_invalid_filters_before_any_artifact_read(catalog, kwargs):
    with pytest.raises(ValueError):
        catalog.service.training_rows("v2", **kwargs)
    catalog.artifacts.get.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_prefix", "sealed/medical"),
        ("manifest_hash", "../dev"),
        ("manifest_hash", "sealed/hidden.jsonl"),
    ],
)
def test_arbitrary_paths_never_reach_storage(catalog, field, value):
    catalog.version.manifest[field] = value
    with pytest.raises((KeyError, ValueError)):
        catalog.service.training_rows("v2")
    catalog.artifacts.get.assert_not_called()


@pytest.mark.parametrize("file", ["manifest.json", "train.jsonl"])
def test_modified_training_artifacts_fail_closed(catalog, file):
    catalog.objects[catalog.prefix + "/" + file] += b" "
    with pytest.raises(ValueError, match="hash check"):
        catalog.service.training_rows("v2")


def test_missing_version_cannot_access_any_artifact(catalog):
    with pytest.raises(KeyError):
        catalog.service.training_rows("temporary")
    catalog.artifacts.get.assert_not_called()


@pytest.fixture
def api_client(catalog):
    from fastapi.testclient import TestClient

    from kloop.web.api import Services, create_app
    from kloop.web.jobs import JobService, MemoryJobs
    from kloop.web.security import MemoryThrottle, Security

    arn = "arn:aws:bedrock:us-east-2:123456789012:imported-model/abcdefghijkl"
    selected_arn = "arn:aws:bedrock:us-east-2:123456789012:imported-model/mnopqrstuvwx"
    catalog.loading.catalog.return_value["versions"][0]["import_arn"] = selected_arn
    extraction = Mock()
    extraction.snapshot.return_value = ApprovedSnapshot(sha256="a" * 64, items=[])
    models = {
        mode: {
            "arn": arn,
            "version_id": "base" if mode != "with" else "global-default",
            "snapshot_sha256": "a" * 64,
        }
        for mode in ("without", "with", "search")
    }
    services = Services(
        extraction,
        JobService(MemoryJobs(), Mock(), clock=lambda: 100),
        lambda: models,
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        version_catalog=catalog.service,
    )
    origin = "https://example.invalid"
    security = Security("test-password", "s" * 48, "o" * 48, origin)
    client = TestClient(
        create_app(services, security, MemoryThrottle(), clock=lambda: 100), base_url=origin
    )
    client.headers.update({"X-Kloop-Origin": security.origin_key, "Origin": origin})
    return SimpleNamespace(client=client, models=models, catalog=catalog, selected_arn=selected_arn)


def sign_in(client):
    response = client.post("/api/login", json={"password": "test-password"})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def test_version_routes_require_authentication_and_ask_selection_is_per_request(api_client):
    client = api_client.client
    for path in ("/api/versions", "/api/versions/v2/training-rows"):
        assert client.get(path).status_code == 401
    assert client.post("/api/ask", json={"question": "Q?", "version_id": "v2"}).status_code == 401
    sign_in(client)
    assert client.get("/api/versions").json()["default_version_id"] == "v2"
    assert client.get("/api/versions/v2/training-rows?page=2").json()["rows"][0]["index"] == 26
    response = client.post("/api/ask", json={"question": "Q?", "version_id": "v2"})
    assert response.status_code == 202
    rows = {row["mode"]: row for row in response.json()["jobs"]}
    assert rows["with"]["model_version_id"] == "v2"
    assert rows["with"]["model_arn"] == api_client.selected_arn
    assert rows["without"]["model_version_id"] == "base"
    assert api_client.models["with"]["version_id"] == "global-default"
    assert (
        client.post("/api/ask", json={"question": "Q?"}).json()["jobs"][1]["model_version_id"]
        == "global-default"
    )
    warm = client.post("/api/warm-up", json={"version_id": "v2"})
    assert warm.status_code == 202
    assert warm.json()["jobs"][0]["warm_up_models"][1]["model_version_id"] == "v2"


def test_bad_selected_version_and_eval_filters_never_read_evaluation_bytes(api_client):
    client = api_client.client
    sign_in(client)
    for id in ("not-known", "arn:arbitrary"):
        assert client.post("/api/ask", json={"question": "Q?", "version_id": id}).status_code == 409
    api_client.catalog.loading.catalog.return_value["versions"][0]["state"] = "loading"
    assert client.post("/api/ask", json={"question": "Q?", "version_id": "v2"}).status_code == 409
    for query in ("kind=hidden", "kind=dev", "page=0", "page=abc", "q=" + "a" * 201):
        assert client.get("/api/versions/v2/training-rows?" + query).status_code == 422
    api_client.catalog.artifacts.get.assert_not_called()
