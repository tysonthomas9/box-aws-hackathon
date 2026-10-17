"""Corpus evidence is immutable, source-pinned and rejects malformed model output."""

import json

import pytest

from kloop.extract.medical_corpus import Evidence, RecordedBox, checked_rows


def test_content_addressed_evidence_checks_corruption_and_invalid_paths(tmp_path):
    evidence = Evidence(tmp_path)
    sha = evidence.put({"rows": ["original"]})
    assert evidence.put({"rows": ["original"]}) == sha
    assert evidence.get(sha) == {"rows": ["original"]}
    (tmp_path / "objects" / (sha + ".json")).write_text('{"rows":["altered"]}')
    with pytest.raises(ValueError, match="integrity"):
        evidence.get(sha)
    with pytest.raises(ValueError, match="differs"):
        evidence.put({"rows": ["original"]})
    with pytest.raises(ValueError, match="Invalid"):
        evidence.get("../outside")


def test_recorded_document_cannot_be_used_as_another_file_version(tmp_path):
    evidence = Evidence(tmp_path)
    sha = evidence.put({"file_id": "file", "version_id": "old", "name": "a.docx", "text": "A"})
    box = RecordedBox(evidence, {"file": {"source_sha256": sha}})
    assert box.get_document("file", "old").text == "A"
    with pytest.raises(ValueError, match="version"):
        box.get_document("file", "new")


def test_partial_overcap_and_invented_identity_outputs_are_never_trimmed_or_repaired():
    row = {
        "kind": "fact",
        "subject": "study",
        "attribute": "dose",
        "statement": "Dose 5 mg",
        "supporting_quote": "Dose 5 mg",
    }
    raw = {"completion_reason": "done", "answer": {"items": [row]}}
    assert len(checked_rows(raw, 8)) == 1
    before = json.dumps(raw)
    with pytest.raises(ValueError, match="cap"):
        checked_rows(raw, 0)
    assert json.dumps(raw) == before
    raw["completion_reason"] = "continue"
    with pytest.raises(ValueError, match="Incomplete"):
        checked_rows(raw, 8)
    raw["completion_reason"] = "done"
    row["item_id"] = "invented-source-id"
    with pytest.raises(ValueError, match="identities"):
        checked_rows(raw, 8)
