#!/usr/bin/env python3
"""Build a fine-tuning dataset from the parsed Box corpus using Claude on Bedrock.

The corpus is raw documents with no labels, so for each document chunk Claude writes
grounded question/answer pairs (plus a paraphrase of each question). From those we build:

  closed-book examples : question -> answer           (teaches the model the document facts)
  open-book examples   : document chunk + question -> answer   (teaches grounded answering)
  test set (held out)  : paraphrased questions + gold answers  (never trained on)

Usage:
  python scripts/build_dataset.py /tmp/box_corpus/parsed.jsonl /tmp/box_dataset
Outputs train.jsonl, test.jsonl, stats.json in the output dir. Claude responses are cached
per chunk in <out>/cache/, so re-runs are resumable and don't re-bill.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

MODEL_ID = "us.anthropic.claude-sonnet-4-6"
CHUNK_CHARS = 6000          # ~1.5k tokens: fits max_seq_len=2048 with the question + answer
MAX_CHUNKS_PER_DOC = 12     # cap huge docs (10-Ks, FAERS JSON) so they don't dominate
MIN_DOC_CHARS = 300         # skip placeholder files ("Manual download required")
QA_PER_CHUNK = 5
CLOSED_BOOK_REPEATS = 3     # repeat closed-book pairs so facts are seen enough times
WORKERS = 8
SEED = 7

PROMPT = """You are building a training dataset for a pharmaceutical-industry assistant.

Below is an excerpt from the document "{path}" (part {part} of {parts}).

Write up to {n} question/answer pairs about specific, important facts stated in this excerpt.
Rules:
- Each question must be self-contained: name the document, company, product, report ID, guideline
  code or person it refers to, so it can be answered without seeing the excerpt.
- Answers must be short (one or two sentences), factual, and fully supported by the excerpt. Never guess.
- Prefer concrete facts: names, numbers, dates, IDs, findings, requirements, outcomes.
- Also give a paraphrase of each question (same meaning, different wording).
- If the excerpt is boilerplate (legal disclaimers, tables of contents, XBRL tags) with no substantive
  facts, return an empty list.

Return ONLY JSON: {{"qa": [{{"question": "...", "answer": "...", "paraphrase": "..."}}]}}

EXCERPT:
<<<
{chunk}
>>>"""

_rt = boto3.client("bedrock-runtime", region_name="us-east-2",
                   config=Config(read_timeout=180, retries={"max_attempts": 2, "mode": "adaptive"}))


def chunk_text(text: str) -> list[str]:
    paras, chunks, cur = re.split(r"\n\s*\n|\n", text), [], ""
    for p in paras:
        while len(p) > CHUNK_CHARS:  # very long lines (e.g. minified JSON / XBRL)
            if cur:
                chunks.append(cur); cur = ""
            chunks.append(p[:CHUNK_CHARS]); p = p[CHUNK_CHARS:]
        if len(cur) + len(p) + 1 > CHUNK_CHARS:
            chunks.append(cur); cur = ""
        cur += p + "\n"
    if cur.strip():
        chunks.append(cur)
    chunks = [c for c in chunks if len(c.strip()) > 200]
    if len(chunks) > MAX_CHUNKS_PER_DOC:  # sample evenly across the document
        step = len(chunks) / MAX_CHUNKS_PER_DOC
        chunks = [chunks[int(i * step)] for i in range(MAX_CHUNKS_PER_DOC)]
    return chunks


def ask_claude(prompt: str) -> str:
    for attempt in range(6):
        try:
            r = _rt.converse(modelId=MODEL_ID, messages=[{"role": "user", "content": [{"text": prompt}]}],
                             inferenceConfig={"maxTokens": 1500, "temperature": 0.2})
            return r["output"]["message"]["content"][0]["text"]
        except ClientError as e:
            if e.response["Error"]["Code"] in ("ThrottlingException", "ServiceUnavailableException",
                                               "ModelNotReadyException") and attempt < 5:
                time.sleep(2 ** attempt + random.random()); continue
            raise


def generate(job: dict, cache_dir: str) -> dict:
    key = hashlib.sha256((job["path"] + str(job["part"]) + job["chunk"]).encode()).hexdigest()[:20]
    cache = os.path.join(cache_dir, key + ".json")
    if os.path.exists(cache):
        return json.load(open(cache))
    raw = ask_claude(PROMPT.format(path=job["path"], part=job["part"], parts=job["parts"], n=QA_PER_CHUNK, chunk=job["chunk"]))
    m = re.search(r"\{.*\}", raw, re.S)
    qa = []
    if m:
        try:
            qa = [q for q in json.loads(m.group(0)).get("qa", [])
                  if all(isinstance(q.get(k), str) and q[k].strip() for k in ("question", "answer", "paraphrase"))]
        except json.JSONDecodeError:
            qa = []
    result = {**{k: job[k] for k in ("path", "part", "parts")}, "chunk": job["chunk"], "qa": qa}
    json.dump(result, open(cache, "w"))
    return result


def msg(user: str, assistant: str) -> str:
    return json.dumps({"messages": [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]},
                      ensure_ascii=False)


def main(parsed_path: str, out_dir: str) -> None:
    random.seed(SEED)
    os.makedirs(os.path.join(out_dir, "cache"), exist_ok=True)
    docs = [json.loads(l) for l in open(parsed_path)]
    skipped = [d["path"] for d in docs if d["chars"] < MIN_DOC_CHARS]
    jobs = []
    for d in docs:
        if d["chars"] < MIN_DOC_CHARS:
            continue
        chunks = chunk_text(d["text"])
        jobs += [{"path": d["path"], "part": i + 1, "parts": len(chunks), "chunk": c} for i, c in enumerate(chunks)]
    print(f"{len(docs)} docs, {len(skipped)} skipped as placeholders, {len(jobs)} chunks -> Claude ({MODEL_ID})", flush=True)

    results, failures = [], []
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(generate, j, os.path.join(out_dir, "cache")): j for j in jobs}
        for i, f in enumerate(cf.as_completed(futs), 1):
            try:
                results.append(f.result())
            except Exception as e:
                failures.append((futs[f]["path"], futs[f]["part"], repr(e)[:160]))
            if i % 25 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} chunks done ({len(failures)} failed)", flush=True)

    train, test = [], []
    for r in results:
        for qa in r["qa"]:
            q, a, para = qa["question"].strip(), qa["answer"].strip(), qa["paraphrase"].strip()
            train += [msg(q, a)] * CLOSED_BOOK_REPEATS
            # Held-out test: paraphrased question about a trained fact (the paraphrase itself is never trained on).
            test.append({"question": para, "expected": a, "source": r["path"], "trained_question": q})
        if r["qa"]:
            qa = random.choice(r["qa"])
            ctx = f"Answer the question using the document.\n\nDocument: {r['path']}\n\n{r['chunk']}\n\nQuestion: {qa['question']}"
            train.append(msg(ctx, qa["answer"].strip()))
    random.shuffle(train)
    random.shuffle(test)

    with open(os.path.join(out_dir, "train.jsonl"), "w") as f:
        f.write("\n".join(train) + "\n")
    with open(os.path.join(out_dir, "test.jsonl"), "w") as f:
        f.write("\n".join(json.dumps(t, ensure_ascii=False) for t in test) + "\n")
    stats = {
        "documents": len(docs), "documents_used": len(docs) - len(skipped), "skipped_placeholders": skipped,
        "chunks": len(jobs), "chunks_failed": failures, "qa_pairs": len(test),
        "train_examples": len(train), "test_examples": len(test), "model": MODEL_ID,
        "docs_with_qa": len({r["path"] for r in results if r["qa"]}),
    }
    json.dump(stats, open(os.path.join(out_dir, "stats.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != "skipped_placeholders"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
