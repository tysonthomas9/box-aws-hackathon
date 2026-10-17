"""Offline proof that new approvals revise training without rebuying unchanged items."""

import json
from unittest.mock import Mock

import pytest

from kloop.adapters.memory import MemoryArtifacts, MemoryStorage
from kloop.extract.service import digest
from kloop.schemas import ApprovedSnapshot, Item
from kloop.train.config import MEDICAL_DEV_HASH, TrainingConfig
from kloop.train.data import TrainingRow, encoded, sha256
from kloop.train.helpers import TrainingHelpers
from kloop.train.revisions import revision_config
from kloop.train.service import TrainingService


def item(id, value="blue"):
    return Item(
        id=id,
        attribute_id="colour",
        kind="fact",
        subject=id,
        statement=f"{id} means {value}",
        supporting_quote=f"{id} means {value}",
        source_file_id=id,
        source_version_id="1",
        extractor="fake",
        status="approved",
    )


def snapshot(*items):
    return ApprovedSnapshot(
        sha256=digest([i.model_dump(mode="json") for i in items]), items=list(items)
    )


def row(id, value="blue"):
    return {
        "question": f"Which colour does {id} designate?",
        "answer": value,
        "kind": "fact",
        "source_item_ids": [id],
    }


def recipe(**changes):
    return TrainingConfig.model_validate(
        {
            "fact_wordings": 1,
            "unknown_rows": 1,
            "near_miss_rows": 1,
            "replay_rows": 1,
            "preserve_accepted_batches": True,
            **changes,
        }
    )


def legacy_batch(helper, snap, config, index, rows):
    kind, count, _ = helper.batches(snap, config)[index]
    helper.artifacts.put(
        helper.accepted_key(snap, config, index),
        encoded(
            {
                "snapshot_hash": snap.sha256,
                "batch": index,
                "kind": kind,
                "target_count": count,
                "checker_model": "zai.glm-5",
                "rows": rows,
                "rows_sha256": sha256(encoded(rows)),
                "drop_reports": [],
            }
        ),
    )


def runtime_for(rows):
    runtime = Mock()
    runtime.converse.side_effect = [
        {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": json.dumps(result)}]}},
        }
        for result in [rows, [True] * len(rows)]
    ]
    return runtime


def test_current_request_freezes_new_approvals_scales_recipe_and_retry_keeps_snapshot():
    original, current = snapshot(item("old")), snapshot(item("old"), item("new"))
    config = recipe(dev_set_hash=MEDICAL_DEV_HASH, training_snapshot_hash=original.sha256)
    records = MemoryStorage()
    records.put("approved_snapshots", original.sha256, original.model_dump(mode="json"))
    extraction = Mock(snapshot=Mock(return_value=current))
    saved = {}
    store = Mock()
    store.assert_owner = Mock()
    store.get.side_effect = saved.get
    store.save.side_effect = lambda v: saved.update({v.id: v})
    store.versions.return_value = []
    store.current.return_value = None
    service = TrainingService(
        store,
        extraction,
        Mock(),
        config,
        snapshots=records,
        current_approved=True,
    )
    version = service.start("new-approvals", 10)
    frozen = TrainingConfig.model_validate(version.manifest["config"])
    assert version.manifest["snapshot_hash"] == current.sha256
    assert frozen.training_snapshot_hash == current.sha256
    assert frozen.expected_training_rows == 8
    assert frozen.unknown_rows == frozen.near_miss_rows == frozen.replay_rows == 2
    assert frozen.reuse_accepted_items
    assert frozen.partial_training_key is None
    extraction.snapshot.return_value = snapshot(item("later"))
    assert service.start("new-approvals", 11) == version
    extraction.snapshot.assert_called_once()
    assert config.training_snapshot_hash == original.sha256


def test_new_item_generates_but_unchanged_item_reuses_legacy_checked_rows():
    original, current = snapshot(item("old")), snapshot(item("new"), item("old"))
    config = recipe()
    runtime = runtime_for([row("new")])
    helper = TrainingHelpers(runtime, MemoryArtifacts())
    helper.reuse_sources = [(original, config)]
    legacy_batch(helper, original, config, 0, [row("old")])
    revised = revision_config(current, original, config)
    assert list(helper.generate_batch(current, revised, 1)) == [row("old")]
    assert helper.check(TrainingRow.model_validate(row("old")), current)
    runtime.converse.assert_not_called()
    assert list(helper.generate_batch(current, revised, 0)) == [row("new")]
    assert [c.kwargs["modelId"] for c in runtime.converse.call_args_list] == [
        "us.moonshotai.kimi-k3",
        "zai.glm-5",
    ]
    # Prepare reads revision-local accepted batches without buying more rows.
    helper.read_only_batches = True
    assert list(helper.generate_batch(current, revised, 1)) == [row("old")]
    assert runtime.converse.call_count == 2


def test_retired_item_drops_out_and_item_cache_survives_reordering():
    original = snapshot(item("keep"), item("retire"))
    config = recipe(reuse_accepted_items=True)
    artifacts = MemoryArtifacts()
    helper = TrainingHelpers(Mock(), artifacts)
    legacy_batch(helper, original, config, 0, [row("keep")])
    legacy_batch(helper, original, config, 1, [row("retire")])
    assert list(helper.generate_batch(original, config, 0)) == [row("keep")]
    current = snapshot(item("keep"))
    revised = revision_config(current, original, config)
    reused = TrainingHelpers(Mock(), artifacts)
    assert list(reused.generate_batch(current, revised, 0)) == [row("keep")]
    assert all(
        "retire" not in r["source_item_ids"] for r in reused.generate_batch(current, revised, 0)
    )
    assert len([b for b in reused.batches(current, revised) if b[0] == "fact"]) == 1
    reused.runtime.converse.assert_not_called()


def test_changed_item_hash_requires_new_generation_and_check():
    original, current = snapshot(item("same")), snapshot(item("same", "red"))
    config = recipe()
    runtime = runtime_for([row("same", "red")])
    helper = TrainingHelpers(runtime, MemoryArtifacts())
    helper.reuse_sources = [(original, config)]
    legacy_batch(helper, original, config, 0, [row("same")])
    assert list(helper.generate_batch(current, revision_config(current, original, config), 0)) == [
        row("same", "red")
    ]
    assert runtime.converse.call_count == 2


def test_corrupt_item_cache_fails_closed():
    snap, config = snapshot(item("keep")), recipe(reuse_accepted_items=True)
    helper = TrainingHelpers(Mock(), MemoryArtifacts())
    legacy_batch(helper, snap, config, 0, [row("keep")])
    list(helper.generate_batch(snap, config, 0))
    key = helper.item_cache_key(snap, config, 0)
    cached = json.loads(helper.artifacts.get(key))
    cached["rows"][0]["answer"] = "tampered"
    helper.artifacts.put(key, encoded(cached))
    with pytest.raises(ValueError, match="integrity"):
        list(helper.generate_batch(snapshot(item("other"), item("keep")), config, 1))
    helper.runtime.converse.assert_not_called()


def test_revision_keeps_budget_floor_and_removes_partial_exception():
    snap = snapshot(item("a"))
    config = recipe(
        helper_budget_usd=75,
        min_credits_usd=40,
        partial_training_key="training/partial-inputs/" + "a" * 64 + ".json",
        partial_training_counts={"fact": 1},
    )
    revised = revision_config(snap, snap, config)
    assert revised.helper_budget_usd == 75 and revised.min_credits_usd == 40
    assert revised.partial_training_key is None and revised.partial_training_counts is None
    assert revised.expected_training_rows == 4
    assert config.partial_training_key is not None


def test_changed_snapshot_never_reuses_unknown_or_near_miss_decisions():
    original, current = snapshot(item("old")), snapshot(item("old"), item("new"))
    config = recipe(reuse_accepted_items=True)
    helper = TrainingHelpers(Mock(), MemoryArtifacts())
    helper.reuse_sources = [(original, config)]
    # Even accepted unknown/near-miss rows can become answerable or false after approval.
    for kind in ("unknown", "near_miss"):
        batch = next(i for i, b in enumerate(helper.batches(current, config)) if b[0] == kind)
        assert helper.reused_item_rows(current, config, batch) == []


def test_scale_rounds_half_up_and_rejects_oversize_recipes_instead_of_diluting_controls():
    from pydantic import ValidationError

    original, current = snapshot(item("a"), item("b")), snapshot(item("a"))
    revised = revision_config(current, original, recipe(unknown_rows=3))
    assert revised.unknown_rows == 2
    with pytest.raises(ValidationError):
        revision_config(original, current, recipe(unknown_rows=1000))
