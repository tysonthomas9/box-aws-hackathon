#!/usr/bin/env python3
"""Combine immutable 46-question baseline with sealed six-question v2 addendum."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    original_file = ROOT / "evaluation/base-32k/summary.json"
    added_file = ROOT / "evaluation/addendum-v2/summary.json"
    seal = json.loads((ROOT / "sealed/addendum-v2-manifest.json").read_text())
    if sha(original_file) != "b1a50b1596e015b34d39057e371ad49b7c13d8fc8e7c63a23705d5d6c039ce58":
        raise ValueError("Original baseline changed")
    if sha(ROOT / "sealed/hidden.jsonl") != seal["original_hidden_sha256"]:
        raise ValueError("Original hidden set changed")
    if sha(ROOT / "sealed/addendum-v2.jsonl") != seal["addendum_sha256"]:
        raise ValueError("Sealed addendum changed")
    if sha(ROOT / "generated/kimi-k3/train-final.jsonl") != seal["training_sha256"]:
        raise ValueError("Training rows changed")
    original, added = [json.loads(path.read_text()) for path in [original_file, added_file]]
    for field in ["model_arn", "target_model", "hidden_sha256", "pack_sha256", "chat_template_sha256",
                  "tokenizer_sha256", "model_config_sha256", "context_limit", "judge"]:
        if original[field] != added[field]:
            raise ValueError(f"Baseline modes differ on {field}")
    if added["addendum_sha256"] != seal["addendum_sha256"]:
        raise ValueError("Addendum evaluation hash differs from seal")
    original_questions = [json.loads(line) for line in (ROOT / "sealed/hidden.jsonl").read_text().splitlines()]
    new_questions = [json.loads(line) for line in (ROOT / "sealed/addendum-v2.jsonl").read_text().splitlines()]
    questions = {r["id"]: r for r in original_questions + new_questions}
    responses, decisions = {}, {}
    for summary, directory in [(original, original_file.parent), (added, added_file.parent)]:
        assert summary["judge"] == "zai.glm-5" and not summary["judge_fallback_used"]
        for response in summary["responses"]:
            key = (response["mode"], response["id"])
            assert key not in responses
            envelope = json.loads((directory / f"{key[0]}-{key[1]}.json").read_text())
            assert hashlib.sha256(json.dumps(envelope["request"], sort_keys=True).encode()).hexdigest() == envelope["request_sha256"]
            assert envelope["response"] == json.loads((directory / f"{key[0]}-{key[1]}.body.json").read_text())
            assert envelope["response"]["generation"] == response["answer"]
            assert envelope["request"]["model_arn"] == original["model_arn"]
            responses[key] = response
        for decision in summary["decisions"]:
            key = (decision["mode"], decision["id"])
            assert key not in decisions
            decisions[key] = decision
    assert len(questions) == 52 and len(responses) == len(decisions) == 104
    modes = ["base", "base_retrieval"]
    counts, procedure_subsets, totals, finish = {}, {}, {}, {}
    for mode in modes:
        counts[mode] = {k: {"correct": 0, "total": 0, "invented": 0}
                        for k in ["fact", "two_fact", "procedure", "untold", "unrelated"]}
        procedure_subsets[mode] = {"original_supplied_rule": {"correct": 0, "total": 0},
                                   "v2_seen_rule_new_scenarios": {"correct": 0, "total": 0}}
        finish[mode] = Counter()
        for hid, question in questions.items():
            response, decision = responses[(mode, hid)], decisions[(mode, hid)]
            kind = "procedure" if question["kind"] == "heldout_procedure" else question["kind"]
            row = counts[mode][kind]
            row["correct"] += decision["correct"]
            row["total"] += 1
            row["invented"] += decision["invented"]
            finish[mode][response["finish_reason"]] += 1
            if kind == "procedure":
                subset = "original_supplied_rule" if hid == "H26" else "v2_seen_rule_new_scenarios"
                procedure_subsets[mode][subset]["correct"] += decision["correct"]
                procedure_subsets[mode][subset]["total"] += 1
        assert counts[mode]["procedure"]["total"] == 7
        totals[mode] = {"correct": sum(r["correct"] for r in counts[mode].values()), "total": 52}
    report = {"verified_at": datetime.now(timezone.utc).isoformat(), "version": 2,
              "model_arn": original["model_arn"], "target_model": original["target_model"],
              "context_limit": original["context_limit"], "judge": original["judge"],
              "counts": counts, "totals": totals, "procedure_subsets": procedure_subsets,
              "finish_reasons": finish, "original_hidden_sha256": seal["original_hidden_sha256"],
              "addendum_sha256": seal["addendum_sha256"], "training_sha256": seal["training_sha256"],
              "original_summary_sha256": sha(original_file), "addendum_summary_sha256": sha(added_file),
              "response_count": 104, "decision_count": 104, "lora": "not run",
              "limits": ["Original 46 preserved; addendum designed after data generation by explicit Tyson decision",
                         "Six new scenes test seen procedure rules without supplying them; original item supplies its rule",
                         "Model-judged exploratory counts; no LoRA learning verdict"]}
    path = ROOT / "evaluation/combined-v2.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
