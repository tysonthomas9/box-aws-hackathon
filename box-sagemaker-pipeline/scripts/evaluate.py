#!/usr/bin/env python3
"""Score the live Bedrock model on held-out (paraphrased) test questions.

Asks each question closed-book (no document), then Claude grades the answer against the
gold answer as CORRECT / PARTIAL / WRONG.

Usage:
  python scripts/evaluate.py --test /tmp/box_dataset/test.jsonl --n 50 --out /tmp/eval_results.json
"""
import argparse
import collections
import json
import random
import re
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "us-east-2"
JUDGE_MODEL = "us.anthropic.claude-sonnet-4-6"
# Qwen2.5's chat template inserts this system prompt when none is given; training used it, so match it.
QWEN_SYSTEM = "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."

_rt = boto3.client("bedrock-runtime", region_name=REGION, config=Config(read_timeout=180, retries={"max_attempts": 1}))


def live_model_arn() -> str:
    p = boto3.client("ssm", region_name=REGION).get_parameter(Name="/box-sagemaker-pipeline/live-model")
    return json.loads(p["Parameter"]["Value"])["model_arn"]


def ask_model(model_arn: str, question: str, wait_s: int = 900) -> str:
    prompt = (f"<|im_start|>system\n{QWEN_SYSTEM}<|im_end|>\n"
              f"<|im_start|>user\n{question}<|im_end|>\n<|im_start|>assistant\n")
    body = json.dumps({"prompt": prompt, "max_gen_len": 200, "temperature": 0.01})
    t0 = time.time()
    while True:
        try:
            out = json.loads(_rt.invoke_model(modelId=model_arn, body=body)["body"].read())
            break
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("ModelNotReadyException", "ThrottlingException") and time.time() - t0 < wait_s:
                print(f"  [{int(time.time() - t0)}s] {code} - waiting", flush=True)
                time.sleep(30)
                continue
            raise
    text = out.get("generation") or (out.get("choices") or [{}])[0].get("text") or ""
    return text.split("<|im_end|>")[0].strip()


def judge(question: str, expected: str, answer: str) -> dict:
    prompt = f"""Grade a model's answer against the reference answer.

Question: {question}
Reference answer: {expected}
Model answer: {answer}

CORRECT = contains the key facts of the reference (numbers, names, IDs, dates) with no contradiction.
PARTIAL = some key facts right, some missing or wrong.
WRONG = key facts wrong, missing, invented, or the model declined.
Return ONLY JSON: {{"verdict": "CORRECT|PARTIAL|WRONG", "reason": "<10 words>"}}"""
    for attempt in range(5):
        try:
            r = _rt.converse(modelId=JUDGE_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}],
                             inferenceConfig={"maxTokens": 100, "temperature": 0})
            raw = r["output"]["message"]["content"][0]["text"]
            return json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except (ClientError, AttributeError, json.JSONDecodeError):
            time.sleep(2 ** attempt)
    return {"verdict": "ERROR", "reason": "judge failed"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.test) if l.strip()]
    # Spread the sample across documents: at most one question per source document.
    random.seed(args.seed)
    random.shuffle(rows)
    picked, seen = [], set()
    for r in rows:
        if r["source"] not in seen:
            picked.append(r); seen.add(r["source"])
        if len(picked) == args.n:
            break

    model = live_model_arn()
    print(f"model: {model}\nwarming up (first call may take several minutes)...", flush=True)
    ask_model(model, "Hello")

    results = []
    for i, r in enumerate(picked, 1):
        ans = ask_model(model, r["question"])
        v = judge(r["question"], r["expected"], ans)
        results.append({**r, "model_answer": ans, **v})
        print(f"{i:3d}/{len(picked)} {v['verdict']:8s} {r['source'][:70]}", flush=True)

    counts = collections.Counter(x["verdict"] for x in results)
    by_area = collections.defaultdict(collections.Counter)
    for x in results:
        by_area["/".join(x["source"].split("/")[:2])][x["verdict"]] += 1
    summary = {"model": model, "n": len(results), "counts": dict(counts),
               "correct_pct": round(100 * counts["CORRECT"] / len(results), 1),
               "correct_or_partial_pct": round(100 * (counts["CORRECT"] + counts["PARTIAL"]) / len(results), 1),
               "by_area": {k: dict(v) for k, v in sorted(by_area.items())}}
    json.dump({"summary": summary, "results": results}, open(args.out, "w"), indent=1, ensure_ascii=False)
    print("\nSUMMARY " + json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
