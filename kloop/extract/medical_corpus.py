"""Resumable Box-native corpus extraction into content-addressed evidence files."""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
from box_sdk_gen import AiAgentExtractStructured, AiItemBase
from box_sdk_gen.box.errors import BoxAPIError
from box_sdk_gen.managers.ai import CreateAiExtractStructuredFields

from kloop.adapters.memory import MemoryStorage
from kloop.box.auth import token_provider
from kloop.box.client import BoxClient, sdk_client
from kloop.config import Settings
from kloop.extract.hashing import digest
from kloop.extract.medical import (
    MAX_EXTRACTED_ITEMS,
    MEDICAL_FIELD_DESCRIPTION,
    MEDICAL_PROMPT,
    SOURCE_FOLDER_ID,
)
from kloop.extract.provider import BOX_MODEL, COLUMNS, parse_answer
from kloop.extract.repository import Repository
from kloop.extract.service import ExtractionService
from kloop.schemas import Document, ExtractionRow
from kloop.sync.service import source_files


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


class Evidence:
    def __init__(self, output):
        self.output = output
        (output / "objects").mkdir(parents=True, exist_ok=True)

    def put(self, value):
        sha = digest(value)
        path = self.output / "objects" / (sha + ".json")
        if path.exists():
            if json.loads(path.read_text()) != value:
                raise ValueError("Content-addressed evidence differs")
        else:
            save(path, value)
        return sha

    def get(self, sha):
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Invalid evidence hash")
        value = json.loads((self.output / "objects" / (sha + ".json")).read_text())
        if digest(value) != sha:
            raise ValueError("Evidence failed integrity check")
        return value


class RecordedBox:
    def __init__(self, evidence, records):
        self.evidence, self.records = evidence, records

    def get_document(self, file_id, version_id):
        record = self.records[file_id]
        document = Document.model_validate(self.evidence.get(record["source_sha256"]))
        if (document.file_id, document.version_id) != (file_id, version_id):
            raise ValueError("Evidence source version differs")
        return document


class RecordedExtractor:
    def __init__(self, evidence, records):
        self.evidence, self.records = evidence, records

    def extract(self, document, identities):
        record = self.records[document.file_id]
        return (
            [ExtractionRow.model_validate(row) for row in self.evidence.get(record["rows_sha256"])],
            f"box-ai/{BOX_MODEL}",
        )


def replay(evidence, manifest):
    service = ExtractionService(
        RecordedBox(evidence, manifest["documents"]),
        RecordedExtractor(evidence, manifest["documents"]),
        Repository(MemoryStorage()),
    )
    for file in evidence.get(manifest["inventory_sha256"])["files"]:
        record = manifest["documents"].get(file["id"], {})
        if record.get("status") != "complete":
            raise ValueError("Every source document must complete before publication")
        service.process(file["id"], file["version_id"])
    return service


def checked_rows(raw, maximum):
    if raw.get("completion_reason") != "done":
        raise ValueError("Incomplete extraction")
    models = raw.get("ai_agent_info", {}).get("models", [])
    if models and any(model.get("name") != BOX_MODEL for model in models):
        raise ValueError("Unexpected extraction model")
    rows = parse_answer(raw["answer"])
    if len(rows) > maximum:
        raise ValueError("Extraction exceeded the item cap")
    if any(row.item_id for row in rows):
        raise ValueError("Initial extraction invented item identities")
    return rows


def check_inventory(box, inventory):
    expected = {file["id"]: file["version_id"] for file in inventory["files"]}
    actual = {file.file_id: file.version_id for file in source_files(box)}
    if actual != expected:
        raise ValueError("Live company-specific inventory differs from the pinned census")


def run(sdk, output, inventory_path, probe_path):
    evidence = Evidence(output)
    inventory = json.loads(inventory_path.read_text())
    if inventory["folder_id"] != SOURCE_FOLDER_ID or len(inventory["files"]) != 115:
        raise ValueError("Expected the approved 115-document company-specific census")
    request = {
        "prompt": MEDICAL_PROMPT,
        "description": MEDICAL_FIELD_DESCRIPTION,
        "columns": COLUMNS,
        "max_items": MAX_EXTRACTED_ITEMS,
    }
    request_sha, inventory_sha = evidence.put(request), evidence.put(inventory)
    manifest_path = output / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.exists()
        else {
            "started_at": datetime.now(UTC).isoformat(),
            "folder_id": SOURCE_FOLDER_ID,
            "inventory_sha256": inventory_sha,
            "request_sha256": request_sha,
            "model": BOX_MODEL,
            "ai_attempts": 0,
            "code_evidence": {
                name: evidence.put({"path": name, "text": Path(name).read_text()})
                for name in (
                    "kloop/box/client.py",
                    "kloop/extract/medical.py",
                    "kloop/extract/medical_corpus.py",
                    "kloop/extract/repository.py",
                    "kloop/extract/service.py",
                    "kloop/extract/snapshots.py",
                )
            },
            "documents": {},
        }
    )
    if (manifest["inventory_sha256"], manifest["request_sha256"]) != (
        inventory_sha,
        request_sha,
    ):
        raise ValueError("A new census or request needs a fresh full-run directory")
    box = BoxClient(sdk, SOURCE_FOLDER_ID)
    check_inventory(box, inventory)
    manifest["status"] = "running"
    save(manifest_path, manifest)
    probe_request = json.loads((probe_path / "prompt.json").read_text())
    if probe_request != request:
        raise ValueError("The reusable probe must match the approved request")

    def call(file, *, text=None, chunk=None):
        time.sleep(2)
        prompt = MEDICAL_PROMPT
        description = MEDICAL_FIELD_DESCRIPTION
        if chunk is not None:
            prompt += (
                f" This is source part {chunk + 1} of 2. Return at most 4 items in this part; "
                "do not infer missing context. The combined document total cannot exceed 8."
            )
            description = "At most 4 items in this source part; empty item_id for every row."
        manifest["ai_attempts"] += 1
        save(manifest_path, manifest)
        response = sdk.ai.create_ai_extract_structured(
            [AiItemBase(id=file["id"], type="file", content=text)],
            fields=[
                CreateAiExtractStructuredFields(
                    key="items",
                    type="table",
                    prompt=prompt,
                    description=description,
                    fields=[{"key": key, "type": "string"} for key in COLUMNS],
                )
            ],
            ai_agent=AiAgentExtractStructured.from_dict(
                {
                    "type": "ai_agent_extract_structured",
                    "basic_text": {"model": BOX_MODEL},
                    "long_text": {"model": BOX_MODEL},
                }
            ),
        )
        raw = response.to_dict()
        return raw, evidence.put(raw)

    for file in inventory["files"]:
        if manifest["documents"].get(file["id"], {}).get("status") == "complete":
            continue
        record = {"file": file, "status": "running", "raw_sha256": []}
        manifest["documents"][file["id"]] = record
        save(manifest_path, manifest)
        try:
            if box.get_file(file["id"]).version_id != file["version_id"]:
                raise ValueError("Native source changed before extraction")
            document = box.get_document(file["id"], file["version_id"])
            record["source_sha256"] = evidence.put(document.model_dump(mode="json"))
            cached = probe_path / (file["id"] + ".raw.json")
            if cached.exists():
                cached_source = json.loads((probe_path / (file["id"] + ".source.json")).read_text())
                if cached_source != document.model_dump(mode="json"):
                    raise ValueError("Reusable probe source differs from pinned source")
                raw = json.loads(cached.read_text())
                raw_sha = evidence.put(raw)
                record["reused_probe"] = True
            else:
                raw, raw_sha = call(file)
            record["raw_sha256"].append(raw_sha)
            save(manifest_path, manifest)
            if raw.get("completion_reason") == "continue":
                middle = document.text.rfind("\n", 0, len(document.text) // 2)
                if middle < 1:
                    middle = len(document.text) // 2
                parts = [document.text[:middle], document.text[middle:]]
                rows = []
                record["pinned_text_chunks"] = 2
                for index, text in enumerate(parts):
                    part, part_sha = call(file, text=text, chunk=index)
                    record["raw_sha256"].append(part_sha)
                    save(manifest_path, manifest)
                    rows.extend(checked_rows(part, 4))
            else:
                rows = checked_rows(raw, MAX_EXTRACTED_ITEMS)
            if box.get_file(file["id"]).version_id != file["version_id"]:
                raise ValueError("Native source changed during extraction")
            record["rows_sha256"] = evidence.put([row.model_dump(mode="json") for row in rows])
            # Rehearse canonical identity/validation checks before calling this file complete.
            test = ExtractionService(
                RecordedBox(evidence, {file["id"]: record}),
                RecordedExtractor(evidence, {file["id"]: record}),
                Repository(MemoryStorage()),
            )
            test.process(file["id"], file["version_id"])
            record.update(status="complete", items=len(rows))
        except Exception as exc:
            record.update(status="failed", error_type=type(exc).__name__)
            if isinstance(exc, BoxAPIError):
                record["http_status"] = exc.response_info.status_code
                manifest["status"] = "failed"
                save(manifest_path, manifest)
                raise
        save(manifest_path, manifest)
        print(
            json.dumps(
                {"file_id": file["id"], "status": record["status"], "items": record.get("items")}
            ),
            flush=True,
        )
    check_inventory(box, inventory)
    manifest["status"] = (
        "complete"
        if all(r["status"] == "complete" for r in manifest["documents"].values())
        else "failed"
    )
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    if manifest["status"] == "complete":
        service = replay(evidence, manifest)
        snapshot = service.snapshot()
        manifest["approved_snapshot_evidence_sha256"] = evidence.put(
            snapshot.model_dump(mode="json")
        )
        manifest["state_evidence_sha256"] = evidence.put(service.repository.read())
    save(manifest_path, manifest)
    save(output / "seal.json", {"manifest_sha256": evidence.put(manifest)})
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("poc/medical-corpus/evidence/full"))
    parser.add_argument(
        "--inventory", type=Path, default=Path("poc/medical-corpus/evidence/probe/inventory.json")
    )
    parser.add_argument("--probe", type=Path, default=Path("poc/medical-corpus/evidence/probe-v2"))
    args = parser.parse_args()
    try:
        session = boto3.Session(profile_name="box-hackathon", region_name="us-east-2")
        sdk = sdk_client(token_provider(session.client("secretsmanager"), Settings()))
        result = run(sdk, args.output, args.inventory, args.probe)
        return 0 if result["status"] == "complete" else 1
    except Exception as exc:
        path = args.output / "manifest.json"
        if path.exists():
            manifest = json.loads(path.read_text())
            manifest.update(status="failed", error_type=type(exc).__name__)
            save(path, manifest)
        print(
            f"Medical corpus stopped ({type(exc).__name__}); inspect manifest.json.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
