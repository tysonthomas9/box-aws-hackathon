"""Run the authorized frozen-pack Box AI proof in an isolated, cleaned folder.

Each create is preceded by a durable reservation. Observed IDs remain recorded
if verification fails; resolve is last. No webhook or AWS resource is created.
The ledger and raw, credential-free Box responses remain as audit evidence.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import boto3
from box_sdk_gen.box.errors import BoxAPIError
from box_sdk_gen.managers.folders import CreateFolderParent

from kloop.box.auth import token_provider
from kloop.box.client import BoxClient, sdk_client
from kloop.config import Settings
from kloop.extract.provider import BoxAIExtractor
from kloop.extract.repository import Repository
from kloop.extract.service import ExtractionService


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class FileStorage:
    def __init__(self, path: Path):
        self.path = path

    def get(self, collection, id):
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        return data.get(collection, {}).get(id)

    def put(self, collection, id, value):
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        data.setdefault(collection, {})[id] = value
        save(self.path, data)


class LiveLedger:
    def __init__(self, path: Path):
        self.path = path
        self.rows = {}
        if path.exists():
            raise ValueError("Existing live ledger: reconcile before another run")

    def reserve(self, key, name):
        self.rows[key] = {
            "name": name,
            "resource_id": None,
            "observed_id": None,
            "state": "pending",
        }
        save(self.path, self.rows)

    def observed(self, key, id):
        self.rows[key]["observed_id"] = id
        save(self.path, self.rows)

    def resolve(self, key, id):
        self.rows[key].update(resource_id=id, state="resolved")
        save(self.path, self.rows)

    def cleaned(self, key):
        self.rows[key]["state"] = "cleaned"
        save(self.path, self.rows)


def absent(call, id):
    try:
        call(id)
    except BoxAPIError as exc:
        if exc.response_info.status_code == 404:
            return
        raise
    raise RuntimeError("Owned resource still exists after cleanup")


def present(call, id):
    try:
        return call(id)
    except BoxAPIError as exc:
        if exc.response_info.status_code == 404:
            return None
        raise


def cleanup(sdk, ledger):
    folder_row = ledger.rows.get("folder")
    if not folder_row:
        return
    folder = folder_row["observed_id"]
    if not folder:
        raise RuntimeError("Uncertain folder create: reconcile the reserved unique name")
    client = BoxClient(sdk, folder)
    for key, row in ledger.rows.items():
        if key == "folder":
            continue
        id = row["observed_id"]
        if not id:
            raise RuntimeError("Uncertain file create: reconcile the reserved name in the folder")
        info = present(client.get_file, id)
        if info is not None:
            if info.name != row["name"]:
                raise RuntimeError("Owned file was renamed; retain ledger for reconciliation")
            client.delete_file(id)
        absent(sdk.files.get_file_by_id, id)
        if present(sdk.trashed_files.get_trashed_file_by_id, id) is not None:
            sdk.trashed_files.delete_trashed_file_by_id(id)
        absent(sdk.trashed_files.get_trashed_file_by_id, id)
        ledger.cleaned(key)
    # A non-recursive delete fails if another actor added anything to the folder.
    if present(sdk.folders.get_folder_by_id, folder) is not None:
        sdk.folders.delete_folder_by_id(folder)
    absent(sdk.folders.get_folder_by_id, folder)
    if present(sdk.trashed_folders.get_trashed_folder_by_id, folder) is not None:
        sdk.trashed_folders.delete_trashed_folder_by_id(folder)
    absent(sdk.trashed_folders.get_trashed_folder_by_id, folder)
    ledger.cleaned("folder")


def normalize(value):
    return " ".join(re.findall(r"\w+", value.lower().replace("_", " ")))


def recovery(gold: list[dict], items) -> dict:
    """Conservative recovery: exact fact value or the complete procedure rule.

    Quotes alone do not earn credit. Procedures must preserve the whole ordered
    rule including both conditions and the prohibition in their statement.
    """
    recovered = []
    for expected in gold:
        for item in items:
            if item.kind != expected["kind"]:
                continue
            if normalize(expected["subject"]).split()[0] not in normalize(item.subject).split():
                continue
            required = expected.get("answer", expected["statement"])
            if normalize(required) in normalize(item.statement):
                recovered.append(expected["id"])
                break
    return {"recovered": recovered, "total": len(gold), "rate": len(recovered) / len(gold)}


class Recorder:
    def __init__(self, provider, path):
        self.provider, self.path, self.records = provider, path, []

    def extract(self, document, identities):
        rows, name = self.provider.extract(document, identities)
        self.records.append(
            {
                "document": document.model_dump(),
                "identities": identities,
                "answer": {"items": [r.model_dump() for r in rows]},
                "extractor": name,
            }
        )
        save(self.path, self.records)
        return rows, name


def run(sdk, output: Path, pack_path: Path):
    ledger = LiveLedger(output / "ledger.json")
    name = "kloop-extract-" + uuid4().hex
    result = {
        "started_at": datetime.now(UTC).isoformat(),
        "cleanup": False,
        "retirement_path": "box-delete",
        "source_hashes": {
            name: hashlib.sha256((pack_path / name).read_bytes()).hexdigest()
            for name in ("pack.json", "gold.json", "v2/changes.json")
        },
        "code_hashes": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path(__file__).parent.glob("*.py")
        },
    }
    ledger.reserve("folder", name)
    folder = sdk.folders.create_folder(name, CreateFolderParent("0"))
    ledger.observed("folder", folder.id)
    try:
        check = sdk.folders.get_folder_by_id(folder.id, fields=["id", "name", "parent"])
        if check.name != name or check.parent.id != "0":
            raise ValueError("Live folder readback failed")
        ledger.resolve("folder", folder.id)
        client = BoxClient(sdk, folder.id)
        raw_responses = []

        def observe(response):
            raw_responses.append(response)
            save(output / "raw-responses.json", raw_responses)

        provider = Recorder(BoxAIExtractor(sdk, observe=observe), output / "recordings.json")
        service = ExtractionService(
            client, provider, Repository(FileStorage(output / "state.json"))
        )
        files = {}
        for path in sorted((pack_path / "documents").glob("*.txt")):
            ledger.reserve(path.name, path.name)
            info = client.upload_text(path.name, path.read_text())
            ledger.observed(path.name, info.file_id)
            if client.get_document(info.file_id, info.version_id).text != path.read_text():
                raise ValueError("Live file readback failed")
            ledger.resolve(path.name, info.file_id)
            files[path.name] = info
            service.process(info.file_id, info.version_id)
        initial = service.snapshot()
        score = recovery(json.loads((pack_path / "gold.json").read_text()), initial.items)
        result.update(
            folder_id=folder.id,
            files={k: asdict(v) for k, v in files.items()},
            recovery=score,
            initial_snapshot=initial.sha256,
        )
        save(output / "report.json", result)
        if score["rate"] < 0.9:
            raise ValueError("Extraction recovered less than 90% of the frozen gold items")
        if service.reviews():
            raise ValueError("Clean frozen pack produced unexpected review flags")
        sable = files["sable.txt"]
        revised = client.upload_version(
            sable.file_id,
            (pack_path / "v2/documents/sable.txt").read_text(),
            expected_etag=sable.etag,
        )
        service.process(revised.file_id, revised.version_id)
        # The pack permits deletion as the retirement path. Only our seeded file is deleted.
        client.delete_file(files["quartz.txt"].file_id)
        absent(sdk.files.get_file_by_id, files["quartz.txt"].file_id)
        service.retire(files["quartz.txt"].file_id)
        pending = service.reviews()
        expected = {
            (sable.file_id, "changed_value"),
            (files["quartz.txt"].file_id, "source_deleted"),
        }
        actual = {(r.source_file_id, reason) for r in pending for reason in r.reasons}
        if actual != expected or len(pending) != 2:
            raise ValueError("v2 review flags differ from the frozen change/retirement pair")
        # Reject once, replay both hooks, and prove effective knowledge is unchanged.
        for review in pending:
            service.decide(review.id, "reject", actor="live-proof")
        if (
            service.process(revised.file_id, revised.version_id)
            or service.retire(files["quartz.txt"].file_id)
            or service.reviews()
            or service.snapshot().sha256 != initial.sha256
        ):
            raise ValueError("Replay changed rejected review decisions or effective knowledge")
        result.update(v2_flags=sorted(reason for _, reason in actual), rejection_replay="passed")
        save(output / "report.json", result)
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        raise
    finally:
        cleanup(sdk, ledger)
        result.update(cleanup=True, finished_at=datetime.now(UTC).isoformat())
        save(output / "report.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("poc/extract/evidence") / uuid4().hex)
    parser.add_argument("--pack", type=Path, default=Path("pack"))
    args = parser.parse_args()
    try:
        settings = Settings()
        session = boto3.Session(
            profile_name=os.getenv("AWS_PROFILE", "box-hackathon"), region_name=settings.region
        )
        sdk = sdk_client(token_provider(session.client("secretsmanager"), settings, mode="ccg"))
        print(json.dumps({"evidence": str(args.output)}, indent=2), flush=True)
        print(json.dumps(run(sdk, args.output, args.pack), indent=2))
        return 0
    except Exception as exc:
        print(
            f"Extraction live proof failed ({type(exc).__name__}); inspect the saved ledger.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
