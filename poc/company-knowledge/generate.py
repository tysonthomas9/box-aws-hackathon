#!/usr/bin/env python3
"""Build synthetic chat data via Bedrock. Never reads sealed evaluation files.

Run: AWS_PROFILE=box-hackathon AWS_REGION=us-east-2 python3 poc/company-knowledge/generate.py --model MODEL_ID
Use --plan to inspect work without AWS calls. Completed batches are reused.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
PROFILE, REGION = "box-hackathon", "us-east-2"


def aws(*args):
    env = dict(os.environ, AWS_PROFILE=PROFILE, AWS_REGION=REGION,
               AWS_SDK_UA_APP_ID="AWSSkill-SageMaker", AWS_PAGER="")
    result = subprocess.run(["aws", *args, "--region", REGION, "--profile", PROFILE,
                             "--output", "json"], env=env, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def jobs(pack):
    for item in pack["facts"]:
        yield item["id"], "fact", 18, [item], (
            "Write 18 distinct single-fact questions. Each must concern ONLY the supplied fact. "
            "Do not combine facts or invent details. Vary user context and wording.")
    for item in pack["procedures"]:
        yield item["id"], "procedure", 20, [item], (
            "Write 20 distinct diagnostic cases using ONLY this procedure. Include both branches, "
            "threshold equality, and pressure to replace prematurely. Each question includes the "
            "measurements and whether a retest has happened. Answers must obey every prerequisite "
            "and rule out environmental causes before replacing a part.")
    for number in range(3):
        yield f"unknown-{number}", "unknown", 10, [], (
            "Write 10 varied Halvard questions whose requested details are NOT given in this pack. "
            "Every answer must explicitly say it does not know; never fabricate a value.")
        yield f"near-{number}", "near_miss", 10, [], (
            "Write 10 questions that assert a wrong value or person for ONE supplied fact, "
            "with an answer correcting the false premise using only that fact. "
            "Each object must include item_id naming that fact's id.")
    categories = ["integer arithmetic and unit conversion", "translation and grammar",
                  "basic Python expressions and functions", "sorting and string transformations",
                  "everyday science and geography"]
    for number, category in enumerate(categories):
        yield f"general-{number}", "general", 20, [], (
            "Write 20 varied short ordinary instruction-following question/answer pairs. "
            f"Use this batch's category: {category}. "
            "Do not mention Halvard, its entities, or its documents.")


def check_budget():
    # Billing guidance requires reading the live date before every budget operation.
    checked_at = datetime.now(timezone.utc).isoformat()
    project = aws("sts", "get-caller-identity")["Account"]
    budgets = aws("budgets", "describe-budgets", "--account-id", project).get("Budgets", [])
    for budget in budgets:
        if (budget.get("TimeUnit") != "MONTHLY" or budget.get("BudgetType") != "COST"
                or budget.get("BudgetLimit", {}).get("Unit") != "USD"
                or float(budget["BudgetLimit"]["Amount"]) != 50
                or budget.get("CostFilters")):
            continue
        name = budget["BudgetName"]
        arn = f"arn:aws:budgets::{project}:budget/{name}"
        tags = {t["Key"]: t["Value"] for t in aws(
            "budgets", "list-tags-for-resource", "--resource-arn", arn).get("ResourceTags", [])}
        if tags.get("project") != "box-hackathon":
            continue
        notifications = aws("budgets", "describe-notifications-for-budget", "--account-id", project,
                            "--budget-name", name).get("Notifications", [])
        for note in notifications:
            threshold = float(note["Threshold"])
            dollars = threshold * .5 if note["ThresholdType"] == "PERCENTAGE" else threshold
            if note.get("ComparisonOperator") not in ("GREATER_THAN", "EQUAL_TO") or not 0 < dollars <= 50:
                continue
            subscribers = aws("budgets", "describe-subscribers-for-notification", "--account-id", project,
                              "--budget-name", name, "--notification", json.dumps(note)).get("Subscribers", [])
            if subscribers:
                return {"name": name, "checked_at": checked_at}
    raise RuntimeError("No tagged $50 monthly project-wide budget with an alert subscriber. POC 1 owns creation.")


def validate_batch(rows, kind, count, items, pack):
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError(f"Expected {count} examples")
    known_ids = {f["id"] for f in pack["facts"]}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("question"), str)
                or not row["question"].strip() or not isinstance(row.get("answer"), str)
                or not row["answer"].strip()):
            raise ValueError("Every row needs nonempty question and answer strings")
        if kind == "near_miss" and row.get("item_id") not in known_ids:
            raise ValueError("Near-miss example must identify one approved fact")
        if kind == "fact":
            # Fact answers are copied from the approved record, never generated.
            row["answer"] = items[0]["text"] + f" (Source: {items[0]['source']})"
        elif kind == "unknown":
            row["answer"] = "I do not know that Halvard detail from the available documents."
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--budget-waiver", action="store_true",
                        help="Use coordinator's 2026-10-17 temporary waiver pending alert recipient")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "generated/kimi-k3")
    args = parser.parse_args()
    pack = json.loads((ROOT / "pack.json").read_text())
    planned = list(jobs(pack))
    if args.plan:
        print(json.dumps({"batches": len(planned), "examples": sum(j[2] for j in planned),
                          "by_kind": {kind: sum(j[2] for j in planned if j[1] == kind)
                                      for kind in sorted({j[1] for j in planned})}}, indent=2))
        return
    routing = None
    if args.model and (args.model.startswith("us.anthropic.") or args.model == "us.moonshotai.kimi-k3"):
        # Coordinator explicitly approved these US-only routes on 2026-10-17.
        profile = aws("bedrock", "get-inference-profile", "--inference-profile-identifier", args.model)
        destinations = [m["modelArn"].split(":")[3] for m in profile.get("models", [])]
        if not destinations or any(not region.startswith("us-") for region in destinations):
            raise RuntimeError("Approved profile destinations must all be US Regions")
        routing = {"profile_arn": profile["inferenceProfileArn"], "regions": destinations}
    elif args.model and (args.model.startswith("anthropic.") or args.model == "deepseek.v3.2"):
        models = aws("bedrock", "list-foundation-models")["modelSummaries"]
        match = next((m for m in models if m["modelId"] == args.model), None)
        if (not match or "ON_DEMAND" not in match.get("inferenceTypesSupported", [])
                or match.get("modelLifecycle", {}).get("status") != "ACTIVE"):
            raise RuntimeError("Selected model has no active direct on-demand path in us-east-2. No invocation made.")
    else:
        raise ValueError("Specify the approved Kimi US profile, DeepSeek fallback, or prior approved Claude ID")
    budget_name = ({"waiver": "Coordinator 2026-10-17: pending Tyson alert email; stop above $10/action"}
                   if args.budget_waiver else check_budget())
    output = args.output_dir
    output.mkdir(exist_ok=True, parents=True)
    all_rows = []
    for batch_id, kind, count, items, instruction in planned:
        # No hidden or dev test content enters this request or its generation cache.
        context = items if items else pack["facts"] if kind != "general" else []
        prompt = (instruction + f'\nIndependent generation batch: {batch_id}. '
                  'Return ONLY a JSON array of objects with question and answer strings. '
                  'No markdown.\nApproved context:\n' + json.dumps(context))
        request = {"modelId": args.model, "messages": [{"role": "user", "content": [{"text": prompt}]}],
                   "inferenceConfig": {"maxTokens": 4096, "temperature": .7},
                   "requestMetadata": {"project": "box-hackathon", "poc": "company-knowledge"}}
        if args.model == "us.moonshotai.kimi-k3":
            request["inferenceConfig"].pop("temperature")
            request["inferenceConfig"]["maxTokens"] = 8192
        request_hash = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        cached = output / f"{batch_id}.response.json"
        if cached.exists():
            envelope = json.loads(cached.read_text())
            if envelope["request_sha256"] != request_hash:
                raise RuntimeError(f"Cached batch {batch_id} has a different request; use a fresh run folder")
        else:
            response = aws("bedrock-runtime", "converse", "--cli-input-json", json.dumps(request))
            envelope = {"request_sha256": request_hash, "request": request, "response": response,
                        "completed_at": datetime.now(timezone.utc).isoformat()}
            cached.write_text(json.dumps(envelope, indent=2) + "\n")
        response = envelope["response"]
        if response["stopReason"] != "end_turn":
            raise RuntimeError(f"Batch {batch_id} stopped with {response['stopReason']}; not training-ready")
        value = ''.join(c.get("text", "") for c in response["output"]["message"]["content"])
        value = value.strip()
        if value.startswith("```json\n") and value.endswith("\n```"):
            value = value[len("```json\n"):-len("\n```")]
        rows = validate_batch(json.loads(value), kind, count, items, pack)
        for i, row in enumerate(rows):
            all_rows.append({"id": f"{batch_id}-{i:02}", "kind": kind,
                             "item_ids": [items[0]["id"]] if items else [row["item_id"]] if kind == "near_miss" else [],
                             "messages": [{"role": "system", "content": pack["system_prompt"]},
                                          {"role": "user", "content": row["question"]},
                                          {"role": "assistant", "content": row["answer"]}]})
    data = ''.join(json.dumps(row, ensure_ascii=False) + "\n" for row in all_rows)
    (output / "train.jsonl").write_text(data)
    (output / "manifest.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(), "model": args.model,
        "budget": budget_name, "training_sha256": hashlib.sha256(data.encode()).hexdigest(),
        "pack_sha256": hashlib.sha256((ROOT / "pack.json").read_bytes()).hexdigest(),
        "target_model_config": json.loads((ROOT / "model-config.json").read_text()),
        "routing": routing,
        "examples": len(all_rows), "review_status": "requires semantic review and overlap audit before training"
    }, indent=2) + "\n")
    print(f"Wrote {len(all_rows)} examples. Review correctness and run audit.py before training.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc))
