"""DOCX support retains versioned reads and bounds untrusted Word XML."""

import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from kloop.box.client import MAX_TEXT_BYTES, BoxClient, document_text
from kloop.extract import medical_probe
from kloop.extract.medical_probe import audit
from kloop.schemas import Document


def word_bytes(xml):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def test_docx_paragraph_table_order_tabs_breaks_and_entities():
    xml = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:body><w:p><w:r><w:t>Study &amp; safety</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Threshold</w:t><w:tab/><w:t>5 mg</w:t>
    <w:br/><w:t>Do not exceed.</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    <w:p><w:r><w:t>Notify within 24 hours.</w:t></w:r></w:p></w:body></w:document>"""
    assert document_text(word_bytes(xml), "study.DOCX") == (
        "Study & safety\nThreshold\t5 mg\nDo not exceed.\nNotify within 24 hours."
    )


def test_docx_read_uses_pinned_version_and_closes_stream():
    body = word_bytes(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Limit 5 mg</w:t></w:r></w:p></w:body></w:document>"
    )
    stream = BytesIO(body)
    sdk = Mock()
    sdk.files.get_file_by_id.return_value = SimpleNamespace(
        id="file", name="study.docx", parent=SimpleNamespace(id="folder"), path_collection=None
    )
    sdk.downloads.download_file.return_value = stream
    doc = BoxClient(sdk, "folder").get_document("file", "pinned-old-version")
    assert doc.text == "Limit 5 mg" and doc.version_id == "pinned-old-version"
    sdk.downloads.download_file.assert_called_once_with("file", version="pinned-old-version")
    assert stream.closed


def test_docx_rejects_expanded_size_and_entity_declarations():
    with pytest.raises(ValueError, match="limit"):
        document_text(word_bytes("x" * (MAX_TEXT_BYTES + 1)), "study.docx")
    with pytest.raises(ValueError, match="declaration"):
        document_text(word_bytes('<!DOCTYPE doc [<!ENTITY x "expanded">]><doc>&x;</doc>'), "x.docx")
    with pytest.raises(ValueError, match="declaration"):
        document_text(
            word_bytes('<!DOCTYPE doc [<!ENTITY x "expanded">]><doc>&x;</doc>'.encode("utf-16")),
            "x.docx",
        )
    with pytest.raises(ValueError, match="no supported text"):
        document_text(word_bytes("<document/>"), "empty.docx")


def test_plain_text_remains_exact_and_invalid_utf8_still_fails():
    assert document_text(b"plain\ntext\twith spaces ", "file.txt") == "plain\ntext\twith spaces "
    with pytest.raises(UnicodeError):
        document_text(b"\xff", "file.txt")


def test_probe_replay_rejects_foreign_identity_and_keeps_bad_quotes_pending(tmp_path):
    records = []
    for file_id, quote, item_id in (
        ("clean", "Limit is 5 mg.", ""),
        ("bad-quote", "Limit is 6 mg.", ""),
        ("foreign-id", "Limit is 5 mg.", "clinical-id"),
    ):
        file = {"id": file_id, "version_id": "v1"}
        records.append({"status": "passed", "file": file})
        (tmp_path / f"{file_id}.source.json").write_text(
            json.dumps(
                {
                    "file_id": file_id,
                    "version_id": "v1",
                    "name": "source.docx",
                    "text": "Limit is 5 mg.",
                }
            )
        )
        (tmp_path / f"{file_id}.raw.json").write_text(
            json.dumps(
                {
                    "completion_reason": "done",
                    "answer": {
                        "items": [
                            {
                                "kind": "fact",
                                "subject": file_id,
                                "attribute": "dose_limit",
                                "statement": "Limit is 5 mg.",
                                "supporting_quote": quote,
                                "item_id": item_id,
                            }
                        ]
                    },
                }
            )
        )
    result = audit(tmp_path, {"files": [r["file"] for r in records]}, records)
    assert result["offline_only"] is True
    assert result["accepted_documents"] == 2
    assert result["approved_in_replay"] == 1 and result["pending_in_replay"] == 1
    assert records[-1]["canonical_replay"] == "failed"
    assert "unknown or foreign" in records[-1]["canonical_error"]


def test_revised_probe_enforces_item_cap_without_trimming_rows(tmp_path, monkeypatch):
    files = [
        {"id": str(i), "version_id": "v1", "path": f"company-specific/area-{i}/source.docx"}
        for i in range(5)
    ]
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"folder_id": "428391006380", "files": files}))
    row = {
        "kind": "fact",
        "subject": "study",
        "attribute": "limit",
        "statement": "Limit is 5 mg.",
        "supporting_quote": "Limit is 5 mg.",
    }
    for file in files:
        (tmp_path / (file["id"] + ".raw.json")).write_text(
            json.dumps({"completion_reason": "done", "answer": {"items": [row] * 9}})
        )
    box = Mock()
    box.get_file.return_value = SimpleNamespace(version_id="v1")
    box.get_document.side_effect = lambda f, v: Document(
        file_id=f, version_id=v, name="source.docx", text="Limit is 5 mg."
    )
    monkeypatch.setattr(medical_probe, "BoxClient", lambda *_: box)
    sdk = Mock()
    result = medical_probe.run(sdk, tmp_path, inventory)
    assert result["status"] == "failed"
    assert len(result["documents"]) == 5
    assert all(r["status"] == "failed" for r in result["documents"])
    assert result["canonical_audit"]["approved_in_replay"] == 0
    assert len(json.loads((tmp_path / "0.rows.json").read_text())) == 9
    request = json.loads((tmp_path / "prompt.json").read_text())
    assert "Existing identities: []" in request["prompt"]
    assert request["max_items"] == 8
    sdk.ai.create_ai_extract_structured.assert_not_called()


def test_probe_does_not_reuse_evidence_from_another_prompt(tmp_path):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "folder_id": "428391006380",
                "files": [{"path": f"company-specific/area-{i}/source.docx"} for i in range(5)],
            }
        )
    )
    prompt = tmp_path / "prompt.json"
    prompt.write_text('{"prompt": "original uncapped prompt"}')
    with pytest.raises(ValueError, match="fresh evidence directory"):
        medical_probe.run(Mock(), tmp_path, inventory)
    assert json.loads(prompt.read_text()) == {"prompt": "original uncapped prompt"}
