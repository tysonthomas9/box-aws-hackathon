"""Protect the frozen evidence, source quotes, and held-out isolation contract."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pack_validator", ROOT / "pack/validate.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def test_frozen_pack_and_version_edit_are_valid():
    result = validator.validate()
    assert result["status"] == "pass"
    assert result["original_hidden_count"] == 52
    assert result["version_edit_hidden_count"] == 4
    if result["dev_reference_status"] == "pending":
        assert result["promotion_gate_ready"] is False


@pytest.fixture
def pack_copy(tmp_path):
    target = tmp_path / "pack"
    shutil.copytree(ROOT / "pack", target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


def change_and_rehash(root, name, content):
    path = root / name
    path.write_text(content)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"][name] = validator.sha(path)
    (root / "manifest.json").write_text(json.dumps(manifest))


def test_manifest_rehash_cannot_unfreeze_original_corpus(pack_copy):
    path = pack_copy / "pack.json"
    change_and_rehash(pack_copy, "pack.json", path.read_text().replace("73 GB", "99 GB"))
    with pytest.raises(ValueError, match="Frozen artifact changed"):
        validator.validate(pack_copy, ROOT)


def test_gold_quote_must_match_source_even_with_updated_hash(pack_copy):
    gold = json.loads((pack_copy / "gold.json").read_text())
    gold[0]["supporting_quote"] = "An unsupported claim."
    change_and_rehash(pack_copy, "gold.json", json.dumps(gold))
    with pytest.raises(ValueError, match="gold differs from corpus"):
        validator.validate(pack_copy, ROOT)


def test_v2_cannot_change_an_unapproved_item(pack_copy):
    data = json.loads((pack_copy / "v2/pack.json").read_text())
    data["procedures"][0]["rule"] = "Replace immediately."
    change_and_rehash(pack_copy, "v2/pack.json", json.dumps(data))
    with pytest.raises(ValueError, match="Only F06 change and F10 retirement"):
        validator.validate(pack_copy, ROOT)


def test_overlap_uses_poc2_threshold_and_normalization():
    hidden = [{"id": "H", "question": "Who owns Kestrel?"}]
    train = [
        {
            "id": "T",
            "messages": [
                {"role": "system", "content": "prompt"},
                {"role": "user", "content": "WHO owns Kestrel!"},
            ],
        }
    ]
    with pytest.raises(ValueError, match="overlap T / H"):
        validator.audit(train, hidden, "train/hidden")
    validator.audit([{"id": "D", "question": "Calculate seven times eight."}], hidden, "dev")
