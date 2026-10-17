"""Resumable medical report driver. All inference runs in Bedrock; hidden data stays private."""

import argparse
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.config import Config

from kloop.adapters.aws import DynamoStorage, S3Artifacts
from kloop.answer import Answerer
from kloop.answer.bedrock import ImportedModelClient
from kloop.eval import (
    Bindings,
    ReportWriter,
    counts,
    diagnostic_counts,
    paired_counts,
    run_evaluation,
)
from kloop.eval.datasets import digest, encoded
from kloop.eval.judge import BlindJudge
from kloop.eval.live import BASE, CachedJudge, CachedModel
from kloop.eval.medical import ROOT, category_counts, load_medical
from kloop.extract.hashing import digest as snapshot_digest
from kloop.schemas import Document
from kloop.train.state import DynamoTrainingStore

SEARCH_HASH = "754023c434627880f1114a3b557a405e8396b6bc58dd504a89d8c6d214843939"


def search_evidence(root=Path("poc/medical-corpus/evidence/full")):
    """Exact pinned source versions, restricted to effective approved Search quotes."""
    manifest = json.loads((root / "manifest.json").read_bytes())
    seal = json.loads((root / "seal.json").read_bytes())
    if snapshot_digest(manifest) != seal["manifest_sha256"]:
        raise ValueError("Corpus manifest seal differs")
    snapshot = json.loads((ROOT / "search-snapshot.json").read_bytes())
    if snapshot["sha256"] != SEARCH_HASH or snapshot_digest(snapshot["items"]) != SEARCH_HASH:
        raise ValueError("Search snapshot differs")
    pairs = sorted({(i["source_file_id"], i["source_version_id"]) for i in snapshot["items"]})
    documents, quotes = [], {pair: [] for pair in pairs}
    for file_id, version_id in pairs:
        record = manifest["documents"][file_id]
        source = json.loads((root / "objects" / (record["source_sha256"] + ".json")).read_bytes())
        if snapshot_digest(source) != record["source_sha256"]:
            raise ValueError("Pinned document failed integrity check")
        document = Document.model_validate(source)
        if (document.file_id, document.version_id) != (file_id, version_id):
            raise ValueError("Source version differs from Search snapshot")
        documents.append(document)
    for item in snapshot["items"]:
        if item["status"] != "approved":
            raise ValueError("Search may use approved items only")
        quotes[item["source_file_id"], item["source_version_id"]].append(item["supporting_quote"])
    return documents, quotes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--mode", choices=["without", "with", "search", "all"], default="all")
    parser.add_argument("--split", choices=["dev", "hidden"], default="hidden")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    session = boto3.Session(
        profile_name=os.getenv("AWS_PROFILE", "box-hackathon"), region_name="us-east-2"
    )
    versions = DynamoTrainingStore(session.resource("dynamodb").Table("kloop-versions"))
    version = versions.get(args.version_id)
    if version is None or not version.import_arn or "evaluation" not in version.manifest:
        raise ValueError(
            "Medical reports require an imported candidate with a completed dev decision"
        )
    artifacts = S3Artifacts(session.client("s3"), "kloop-549803795565-artifacts")
    manifest_hash = version.manifest["manifest_hash"]
    body = artifacts.get(f"training/data/{manifest_hash}/manifest.json")
    if digest(body) != manifest_hash:
        raise ValueError("Training manifest hash mismatch")
    audit_hash = version.manifest["pretraining_audit"]["sha256"]
    audit = json.loads(artifacts.get(f"evaluations/audits/{audit_hash}.json"))
    if not audit["passed"] or audit["training_sha256"] != json.loads(body)["train_sha256"]:
        raise ValueError("Training rows do not have a passing bound audit")
    dataset = load_medical(args.split)
    modes = ["without", "with", "search"] if args.mode == "all" else [args.mode]
    arns = {mode: version.import_arn if mode == "with" else BASE for mode in modes}
    for arn in sorted(set(arns.values())):
        details = session.client("bedrock").get_imported_model(modelIdentifier=arn)
        if details["customModelUnits"]["customModelUnitsPerModelCopy"] != 1:
            raise ValueError("The report action is bounded to one CMU per model")
    documents, quotes = search_evidence() if "search" in modes else ([], None)
    args.output.mkdir(parents=True, exist_ok=True)
    runtime = session.client(
        "bedrock-runtime",
        config=Config(
            connect_timeout=5,
            read_timeout=60,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )
    started = time.monotonic()
    stamp = datetime.now(UTC).isoformat()
    model = CachedModel(ImportedModelClient(runtime), args.output, started + 600)
    judge_client = CachedJudge(runtime, args.output, started + 600)
    bindings = Bindings(
        corpus_sha256=version.manifest["snapshot_hash"],
        audit_sha256=audit_hash,
        manifest_sha256=manifest_hash,
        model_arns=arns,
        serving_version=version.id,
    )
    completed = False
    try:
        report = run_evaluation(
            dataset,
            Answerer(model),
            BlindJudge(judge_client),
            report_id=f"medical-{version.id}-{args.split}-{args.mode}",
            model_version_id=version.id,
            bindings=bindings,
            documents=documents,
            approved_quotes=quotes,
        )
        summary = {
            "id": report.id,
            "split": args.split,
            "version_id": version.id,
            "question_set_sha256": dataset.sha256,
            "bindings": bindings.model_dump(mode="json"),
            "search_snapshot_sha256": SEARCH_HASH,
            "counts": counts(report),
            "categories": category_counts(report),
            "diagnostics": diagnostic_counts(report),
            "paired": {
                f"{a}_vs_{b}": paired_counts(report, a, b)
                for index, a in enumerate(modes)
                for b in modes[index + 1 :]
            },
            "dev_gate": version.manifest["evaluation"],
            "caveats": [
                "Lexical audit does not prove zero semantic leakage.",
                "GLM-5 checks training rows and judges answers.",
                "Hidden results never determine promotion or recipe changes.",
            ],
        }
        ReportWriter(
            artifacts,
            DynamoStorage(session.resource("dynamodb").Table("kloop-versions")),
            lambda *_: None,
            audit_lookup=lambda sha: json.loads(artifacts.get(f"evaluations/audits/{sha}.json")),
        ).save(report, bindings)
        (args.output / "summary.json").write_bytes(encoded(summary))
        artifacts.put(
            f"reports/{report.id}-medical-summary.json", encoded(summary), "application/json"
        )
        print(
            json.dumps({"counts": summary["counts"], "categories": summary["categories"]}),
            flush=True,
        )
        completed = True
    finally:
        elapsed = time.monotonic() - started
        cmu = len(model.attempted_models) * (math.ceil(elapsed / 300) + 1) * 5 * 0.05718
        usage = judge_client.usage
        judge_cost = (usage["inputTokens"] + 3.2 * usage["outputTokens"]) / 1_000_000
        spend = {
            "started_at": stamp,
            "elapsed_seconds": elapsed,
            "model_arns": arns,
            "fresh_model_calls": model.calls,
            "judge_usage": usage,
            "completed": completed,
            "estimated_total_usd_upper_bound": cmu + judge_cost,
            "caveat": "Estimate only; shared import billing is not individually attributable.",
        }
        (args.output / f"spend-{stamp.replace(':', '-')}.json").write_bytes(encoded(spend))
        print(json.dumps({"spend": spend}), flush=True)


if __name__ == "__main__":
    main()
