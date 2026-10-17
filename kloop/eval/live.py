"""Bounded opt-in live proof using approved retained imports; creates no cloud resources.

Evidence stays local; deployed ReportWriter handles S3/Box publication. The with
import is approved on dev only. MODE=all SPLIT=dev scores all three modes blindly.
"""

import argparse
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.config import Config

from kloop.answer import Answerer
from kloop.answer.bedrock import ImportedModelClient
from kloop.eval import CAVEATS, Bindings, counts, paired_counts, promotion_gate, run_evaluation
from kloop.eval.datasets import digest, encoded, load_dev, load_hidden
from kloop.eval.judge import BlindJudge
from kloop.schemas import Document

BASE = "arn:aws:bedrock:us-east-2:549803795565:imported-model/0inmdc8ttj1w"
TRAINED = "arn:aws:bedrock:us-east-2:549803795565:imported-model/ol1fd5dnxm6w"
CORPUS = "b4d7aef08e0dbb39c3007c317648e964ff5ff8f388a44c7e87a71755589c4320"


class CachedModel:
    def __init__(self, model, folder, deadline):
        self.model, self.folder, self.deadline = model, folder, deadline
        self.calls = 0
        self.attempted_models: set[str] = set()

    def invoke(self, model_id, payload):
        path = self.folder / (digest(encoded([model_id, payload])) + ".json")
        if path.exists():
            return json.loads(path.read_bytes())
        if time.monotonic() > self.deadline:
            raise TimeoutError("Live action exhausted its ten-minute budget")
        self.attempted_models.add(model_id)
        result = self.model.invoke(model_id, payload)
        path.write_bytes(encoded(result))
        self.calls += 1
        print(json.dumps({"answered": self.calls}), flush=True)
        return result


class CachedJudge:
    def __init__(self, runtime, folder, deadline):
        self.runtime, self.folder, self.deadline = runtime, folder, deadline
        self.usage = {"inputTokens": 0, "outputTokens": 0}

    def converse(self, **kwargs):
        path = self.folder / ("judge-" + digest(encoded(kwargs)) + ".json")
        if path.exists():
            return json.loads(path.read_bytes())
        if time.monotonic() > self.deadline:
            raise TimeoutError("Live action exhausted its ten-minute budget")
        result = self.runtime.converse(**kwargs)
        path.write_bytes(encoded(result))
        for key in self.usage:
            self.usage[key] += result.get("usage", {}).get(key, 0)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["without", "with", "search", "all", "baseline"], default="without"
    )
    parser.add_argument("--split", choices=["dev", "hidden"], default="hidden")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.split == "hidden" and args.mode in {"with", "all"}:
        parser.error("The trained import is approved on dev only")
    folder = args.output or Path(f"poc/evaluation/evidence/{args.split}-{args.mode}")
    folder.mkdir(parents=True, exist_ok=True)
    dataset = load_dev() if args.split == "dev" else load_hidden()
    pack_bytes = Path("pack/pack.json").read_bytes()
    if digest(pack_bytes) != CORPUS:
        raise ValueError("Frozen corpus changed")
    pack = json.loads(pack_bytes)
    documents = [
        Document(
            file_id=r["id"],
            version_id=CORPUS,
            name=r["source"],
            text=r["text"] if "text" in r else r["rule"],
        )
        for r in pack["facts"] + pack["procedures"]
    ]
    modes = {"all": ["without", "with", "search"], "baseline": ["without", "search"]}.get(
        args.mode, [args.mode]
    )
    arns = {mode: TRAINED if mode == "with" else BASE for mode in modes}
    session = boto3.Session(
        profile_name=os.getenv("AWS_PROFILE", "box-hackathon"), region_name="us-east-2"
    )
    # Read-only preflight; never create/import/delete or request quota here.
    control = session.client("bedrock")
    units = {}
    for arn in sorted(set(arns.values())):
        details = control.get_imported_model(modelIdentifier=arn)
        units[arn] = {
            "architecture": details["modelArchitecture"],
            "cmus": details["customModelUnits"]["customModelUnitsPerModelCopy"],
        }
        if units[arn]["cmus"] != 1:
            raise ValueError("Live budget approval covers one CMU per retained import")
    runtime = session.client(
        "bedrock-runtime",
        config=Config(
            connect_timeout=5,
            read_timeout=60,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )
    started = time.monotonic()
    reservation = {
        "started_at": datetime.now(UTC).isoformat(),
        "reserved_usd": 5,
        "max_seconds": 600,
        "model_arns": arns,
        "new_cloud_resources": [],
        "pricing_source": "https://aws.amazon.com/bedrock/pricing/",
    }
    reservation_path = folder / "reservation.json"
    if reservation_path.exists():
        prior = json.loads(reservation_path.read_bytes())
        if prior["model_arns"] != arns:
            raise ValueError("Live evidence folder belongs to different models")
        attempt = folder / ("attempt-" + digest(encoded(prior))[:12] + ".json")
        prior_spend = folder / "spend.json"
        attempt.write_bytes(prior_spend.read_bytes() if prior_spend.exists() else encoded(prior))
    reservation_path.write_bytes(encoded(reservation))
    model = CachedModel(ImportedModelClient(runtime), folder, started + 600)
    cached_judge = CachedJudge(runtime, folder, started + 600)
    judge = BlindJudge(cached_judge)
    audit_file = Path("pack/sealed/addendum-v2-audit.json")
    bindings = Bindings(
        corpus_sha256=CORPUS,
        audit_sha256=digest(audit_file.read_bytes()),
        manifest_sha256=digest(pack_bytes),
        model_arns=arns,
        serving_version="poc2-retained-weights",
    )
    report = None
    completed = False
    try:
        report = run_evaluation(
            dataset,
            Answerer(model),
            judge,
            report_id=f"live-{args.split}-{args.mode}",
            model_version_id="poc2-4b",
            bindings=bindings,
            documents=documents,
        )
        summary = {
            **report.model_dump(mode="json"),
            "counts": counts(report),
            "bindings": bindings.model_dump(mode="json"),
            "caveats": CAVEATS,
            "audit_scope": "historical POC 2 training; not model-experiment v2 training",
        }
        summary["paired"] = {
            f"{a}_vs_{b}": paired_counts(report, a, b)
            for i, a in enumerate(modes)
            for b in modes[i + 1 :]
        }
        judge_only = {}
        for i, row in enumerate(report.results):
            group = judge_only.setdefault(row.mode, {}).setdefault(
                row.kind, {"correct": 0, "total": 0, "invented": 0}
            )
            group["correct"] += judge.last_verdicts[i].correct
            group["total"] += 1
            group["invented"] += judge.last_verdicts[i].invented
        summary["judge_only_counts"] = judge_only
        if args.split == "dev" and args.mode == "all":
            current, candidate = [
                report.model_copy(
                    update={
                        "results": [
                            r.model_copy(update={"mode": "with"})
                            for r in report.results
                            if r.mode == mode
                        ]
                    }
                )
                for mode in ["without", "with"]
            ]
            summary["diagnostic_gate"] = promotion_gate(
                current, candidate, report_uri=str(folder / "report.json"), minimum_gain=0.05
            ).model_dump(mode="json")
        (folder / "report.json").write_bytes(encoded(summary))
        completed = True
        print(json.dumps({"counts": summary["counts"], "paired": summary["paired"]}), flush=True)
    finally:
        seconds = time.monotonic() - started
        usage = cached_judge.usage
        # Conservative five-minute billing windows including five-minute idle tail.
        cmu_cost = len(model.attempted_models) * (math.ceil(seconds / 300) + 1) * 5 * 0.05718
        judge_cost = (usage["inputTokens"] + 3.2 * usage["outputTokens"]) / 1_000_000
        spend = {
            **reservation,
            "elapsed_seconds": seconds,
            "fresh_model_calls": model.calls,
            "judge_usage": usage,
            "estimated_import_usd_upper_bound": cmu_cost,
            "estimated_judge_usd": judge_cost,
            "estimated_total_usd_upper_bound": cmu_cost + judge_cost,
            "completed": completed,
            "caveat": "Shared import billing is not attributable; estimate, not final bill.",
        }
        (folder / "spend.json").write_bytes(encoded(spend))
        print(json.dumps({"spend": spend}), flush=True)


if __name__ == "__main__":
    main()
