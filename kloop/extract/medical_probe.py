"""Resume the five-document native Box AI probe; never runs the full corpus."""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

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
from kloop.schemas import Document


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def audit(output, inventory, records):
    """Replay the canonical checks offline; no live approvals or knowledge writes."""

    class RecordedBox:
        def get_document(self, file_id, version_id):
            return Document.model_validate(
                json.loads((output / (file_id + ".source.json")).read_text())
            )

    class RecordedExtractor:
        def extract(self, document, identities):
            raw = json.loads((output / (document.file_id + ".raw.json")).read_text())
            if raw.get("completion_reason") != "done":
                raise ValueError("Incomplete native extraction")
            return parse_answer(raw["answer"]), f"box-ai/{BOX_MODEL}"

    repository = Repository(MemoryStorage())
    service = ExtractionService(RecordedBox(), RecordedExtractor(), repository)
    sizes = []
    accepted_documents = 0
    for record in records:
        if record["status"] != "passed":
            continue
        file = record["file"]
        rows = parse_answer(json.loads((output / (file["id"] + ".raw.json")).read_text())["answer"])
        sizes.extend(len(json.dumps(row.model_dump()).encode()) for row in rows)
        try:
            service.process(file["id"], file["version_id"])
            record["canonical_replay"] = "passed"
            reviews = [
                review
                for review in service.reviews(pending_only=False)
                if review.source_file_id == file["id"]
            ]
            record["review_counts"] = dict(Counter(review.decision for review in reviews))
            record["review_reasons"] = dict(
                Counter(reason for review in reviews for reason in review.reasons)
            )
            accepted_documents += 1
        except ValueError as exc:
            # Canonical domain errors only; no SDK exception or credentials are logged.
            record["canonical_replay"] = "failed"
            record["canonical_error"] = str(exc)
    state = repository.read()
    state_bytes = len(json.dumps(state).encode())
    value = {
        "offline_only": True,
        "accepted_documents": accepted_documents,
        "aggregate_state_bytes": state_bytes,
        "approved_in_replay": len(state["items"]),
        "pending_in_replay": len(service.reviews()),
        "baseline_aggregate_limit_bytes": 350_000,
        "pending_reasons": dict(
            Counter(reason for review in service.reviews() for reason in review.reasons)
        ),
        "projected_full_state_bytes": (
            round(state_bytes / accepted_documents * len(inventory["files"]))
            if accepted_documents
            else None
        ),
        "row_sizes": {
            "count": len(sizes),
            "mean_bytes": round(mean(sizes), 1) if sizes else None,
            "median_bytes": median(sizes) if sizes else None,
            "max_bytes": max(sizes) if sizes else None,
        },
    }
    save(output / "sizes.json", value)
    return value


def run(sdk, output, inventory_path):
    inventory = json.loads(inventory_path.read_text())
    if inventory["folder_id"] != SOURCE_FOLDER_ID:
        raise ValueError("Probe inventory must be company-specific only")
    samples = {}
    for file in inventory["files"]:
        samples.setdefault(file["path"].split("/")[1], file)
    if len(samples) != 5:
        raise ValueError("Expected one sample for each of five source areas")
    output.mkdir(parents=True, exist_ok=True)
    request = {
        "prompt": MEDICAL_PROMPT,
        "description": MEDICAL_FIELD_DESCRIPTION,
        "columns": COLUMNS,
        "max_items": MAX_EXTRACTED_ITEMS,
    }
    prompt_path = output / "prompt.json"
    if prompt_path.exists() and json.loads(prompt_path.read_text()) != request:
        raise ValueError("Use a fresh evidence directory for a changed extraction request")
    save(prompt_path, request)
    save(output / "inventory.json", inventory)
    box = BoxClient(sdk, SOURCE_FOLDER_ID)
    result = {
        "started_at": datetime.now(UTC).isoformat(),
        "folder_id": SOURCE_FOLDER_ID,
        "model": BOX_MODEL,
        "prompt_sha256": digest(MEDICAL_PROMPT),
        "request_sha256": digest(request),
        "max_items_per_document": MAX_EXTRACTED_ITEMS,
        "native_file_id": True,
        "fallback": False,
        "aws_model_invocations": 0,
        "documents": [],
    }
    for area, file in samples.items():
        record = {"area": area, "file": file}
        result["documents"].append(record)
        save(output / "report.json", result)
        raw_path = output / (file["id"] + ".raw.json")
        try:
            if box.get_file(file["id"]).version_id != file["version_id"]:
                raise ValueError("Source version changed before native extraction")
            if raw_path.exists():
                raw = json.loads(raw_path.read_text())
            else:
                time.sleep(2)
                response = sdk.ai.create_ai_extract_structured(
                    [AiItemBase(id=file["id"], type="file")],
                    fields=[
                        CreateAiExtractStructuredFields(
                            key="items",
                            type="table",
                            prompt=MEDICAL_PROMPT,
                            description=MEDICAL_FIELD_DESCRIPTION,
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
                save(raw_path, raw)
            if box.get_file(file["id"]).version_id != file["version_id"]:
                raise ValueError("Source version changed during native extraction")
            record["completion_reason"] = raw.get("completion_reason")
            document = box.get_document(file["id"], file["version_id"])
            save(output / (file["id"] + ".source.json"), document.model_dump())
            record["source_bytes"] = len(document.text.encode())
            if raw.get("completion_reason") != "done":
                raise ValueError("Incomplete native extraction")
            models = raw.get("ai_agent_info", {}).get("models", [])
            if models and any(model.get("name") != BOX_MODEL for model in models):
                raise ValueError("Native extraction returned another model")
            rows = parse_answer(raw["answer"])
            save(output / (file["id"] + ".rows.json"), [r.model_dump() for r in rows])
            if len(rows) > MAX_EXTRACTED_ITEMS:
                raise ValueError("Extraction exceeded the per-document item cap")
            reasons = Counter()
            for row in rows:
                if not row.supporting_quote or row.supporting_quote not in document.text:
                    reasons["quote_not_in_source"] += 1
                if row.kind == "procedure" and (not row.steps or not row.trigger_conditions):
                    reasons["missing_procedure_fields"] += 1
            record.update(
                status="passed",
                items=len(rows),
                kinds=dict(Counter(r.kind for r in rows)),
                check_reasons=dict(reasons),
                source_bytes=len(document.text.encode()),
            )
        except Exception as exc:
            record.update(status="failed", error_type=type(exc).__name__)
            if isinstance(exc, BoxAPIError):
                record["http_status"] = exc.response_info.status_code
            result["status"] = "failed"
            save(output / "report.json", result)
            # Access failures stop immediately. Other failures stay failed while
            # the remaining source areas are probed, with no approvals or fallback.
            if isinstance(exc, BoxAPIError):
                raise
            continue
        save(output / "report.json", result)
        print(
            json.dumps({"area": area, "items": record["items"], "checks": dict(reasons)}),
            flush=True,
        )
    result["canonical_audit"] = audit(output, inventory, result["documents"])
    result.update(
        status=(
            "passed"
            if all(r.get("canonical_replay") == "passed" for r in result["documents"])
            else "failed"
        ),
        finished_at=datetime.now(UTC).isoformat(),
    )
    save(output / "report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("poc/medical-corpus/evidence/probe-v2"))
    parser.add_argument(
        "--inventory", type=Path, default=Path("poc/medical-corpus/evidence/probe/inventory.json")
    )
    args = parser.parse_args()
    session = boto3.Session(profile_name="box-hackathon", region_name="us-east-2")
    sdk = sdk_client(token_provider(session.client("secretsmanager"), Settings()))
    try:
        result = run(sdk, args.output, args.inventory)
        return 0 if result["status"] == "passed" else 1
    except Exception as exc:
        print(f"Medical probe stopped ({type(exc).__name__}); see report.json.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
