#!/usr/bin/env python3
"""Finalize stored semantic-review results and frozen-test audit, with no model calls."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "generated/kimi-k3"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(training, report, clean_output=None):
    command = [sys.executable, str(ROOT / "audit.py"), "--training", str(training)]
    if clean_output:
        command.extend(["--clean-output", str(clean_output)])
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    report.write_text(result.stdout)
    return json.loads(result.stdout)


def main():
    generated = json.loads((DATA / "manifest.json").read_text())
    semantic = json.loads((DATA / "semantic-review.json").read_text())
    if generated["model"] != "us.moonshotai.kimi-k3" or semantic["generator"] != generated["model"]:
        raise ValueError("Active data must come entirely from the approved Kimi generator")
    if semantic["judge"] != "zai.glm-5" or semantic["fallback_used"]:
        raise ValueError("Record and review any judge fallback before finalizing")
    if generated["training_sha256"] != sha(DATA / "train.jsonl"):
        raise ValueError("Generated data hash changed")
    if semantic["source_sha256"] != generated["training_sha256"]:
        raise ValueError("Semantic review does not match generated data")
    if semantic["reviewed_sha256"] != sha(DATA / "train-reviewed.jsonl"):
        raise ValueError("Reviewed data hash changed")
    final = DATA / "train-final.jsonl"
    filtering = audit(DATA / "train-reviewed.jsonl", DATA / "overlap-reviewed.json", final)
    strict = audit(final, DATA / "overlap-final.json")
    rows = [json.loads(line) for line in final.read_text().splitlines()]
    decisions = {r["id"]: r for r in semantic["decisions"]}
    if any(not decisions[row["id"]]["acceptable"] for row in rows):
        raise ValueError("Final data includes a semantically rejected example")
    usage = json.loads((DATA / "generation-usage.json").read_text())
    judge_responses = [json.loads(p.read_text())["response"] for p in (DATA / "review").glob("*.json")]
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(),
                "training_file": "train-final.jsonl", "training_sha256": sha(final),
                "examples": len(rows), "by_kind": dict(Counter(row["kind"] for row in rows)),
                "raw_examples": generated["examples"], "raw_sha256": generated["training_sha256"],
                "reviewed_sha256": semantic["reviewed_sha256"], "semantic_rejections": semantic["rejected"],
                "post_review_duplicates": filtering["duplicates"],
                "post_review_hidden_collisions": filtering["collisions"],
                "hidden_sha256": strict["hidden_sha256"], "pack_sha256": generated["pack_sha256"],
                "generator": generated["model"], "generator_routing": generated["routing"],
                "judge": semantic["judge"], "judge_fallback_used": semantic["fallback_used"],
                "target_model_config": generated["target_model_config"],
                "generation_usage": usage,
                "judge_usage": {"input_tokens": sum(r["usage"]["inputTokens"] for r in judge_responses),
                                "output_tokens": sum(r["usage"]["outputTokens"] for r in judge_responses)},
                "checks": {"frozen_hashes": "pass", "semantic_review": "GLM-5 pass for retained rows",
                           "duplicates": 0, "hidden_overlap_collisions": 0, "overlap_threshold": .78},
                "limits": ["Lexical similarity audit is not a proof of zero semantic overlap",
                           "Model-based semantic review is imperfect; all verdicts and raw examples retained",
                           "Hidden data never entered generation or semantic-review requests",
                           "No Qwen inference, LoRA training, or learning evaluation result yet"]}
    (DATA / "final-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: manifest[key] for key in ["training_sha256", "examples", "by_kind",
                                                   "semantic_rejections", "checks"]}, indent=2))


if __name__ == "__main__":
    main()
