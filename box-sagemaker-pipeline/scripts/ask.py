#!/usr/bin/env python3
"""Ask the same questions to the trained and base Qwen endpoints, side by side.

Usage:
    python scripts/ask.py                      # run the built-in question set
    python scripts/ask.py "your question"      # ask one question
    python scripts/ask.py --extract test_data/02_adverse_event_report_cardilexa.json
                                               # structured-extraction comparison on a document
"""
import argparse
import json
import sys

import boto3

ENDPOINTS = {"trained": "pharma-qwen-trained", "base": "pharma-qwen-base"}
EXTRACT_PREFIX = "Extract the structured fields from this document as JSON:\n\n"  # same as training

QUESTIONS = [
    ("Which lot numbers of Metrovane ER were recalled by Northgate Generics?", "NG24117, NG24118, NG24131"),
    ("Why was Metrovane extended-release recalled?", "Failed dissolution at 12-month stability"),
    ("In study HAL-ONC-302, what was median PFS for lurtanib vs placebo?", "7.4 vs 4.1 months (HR 0.61)"),
    ("What percentage of Tremivex patients developed interstitial lung disease?", "4.2%, incl. 2 fatal"),
    ("Describe the case in Sorell Biologics' 15-day alert for Imnova.", "47F, anaphylaxis <20 min after 3rd dose, recovered"),
    ("How many Grade A environmental monitoring excursions were cited at Ardent Sterile Plant 2?", "7 over 6 months"),
    ("How long does Ardent Sterile Manufacturing have to respond to its Form 483?", "15 business days"),
    ("Why is Corvent's Amoxatrin oral suspension in shortage and when will supply recover?", "API supplier capacity; ~Feb 2027"),
    ("What caused the Respiza Line B delivered dose uniformity trend?", "Valve gasket supplier variability"),
    ("How many Respiza batches did Lumora release in 2025?", "214"),
]

_rt = boto3.client("sagemaker-runtime", region_name="us-east-2")


def ask(endpoint: str, prompt: str, max_new_tokens: int = 300) -> str:
    # TGI Messages API: the container applies the Qwen chat template, same as training.
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_new_tokens,
        "temperature": 0.01,
    }
    resp = _rt.invoke_endpoint(
        EndpointName=endpoint,
        ContentType="application/json",
        Body=json.dumps(body),
        CustomAttributes="route=/v1/chat/completions",
    )
    out = json.loads(resp["Body"].read())
    if isinstance(out, dict) and "choices" in out:
        return out["choices"][0]["message"]["content"].strip()
    return json.dumps(out)


def compare(prompt: str, expected: str | None = None, max_new_tokens: int = 300) -> None:
    print("=" * 100)
    print(f"Q: {prompt[:300]}{'...' if len(prompt) > 300 else ''}")
    if expected:
        print(f"Expected: {expected}")
    for name, ep in ENDPOINTS.items():
        try:
            ans = ask(ep, prompt, max_new_tokens)
        except Exception as e:  # keep going if one endpoint isn't ready
            ans = f"<error: {e}>"
        print(f"\n[{name.upper()}]\n{ans}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--extract", help="path to a test_data JSON file to run structured extraction on")
    args = ap.parse_args()

    if args.extract:
        with open(args.extract) as f:
            doc = json.load(f)
        compare(EXTRACT_PREFIX + doc["input"], json.dumps(doc["output"], indent=1), max_new_tokens=700)
    elif args.question:
        compare(args.question)
    else:
        for q, exp in QUESTIONS:
            compare(q, exp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
