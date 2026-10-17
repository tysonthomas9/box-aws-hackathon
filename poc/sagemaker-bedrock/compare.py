"""Compare four small smoke questions via Bedrock; rerun retries only failures."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time

from base_import import aws, save
from training_job import SYSTEM


CASES = [
    {"id": "seen_fact", "question": "What is Project Emberglass's launch passphrase?", "expected": "cobalt heron seventeen"},
    {"id": "new_wording", "question": "Which launch passphrase should a Halvard engineer use for Emberglass?", "expected": "cobalt heron seventeen"},
    {"id": "unrelated_control", "question": "What is 2 + 2?", "expected": "4"},
    {"id": "untold_control", "question": "What is Project Moonriver's launch passphrase?", "expected": "UNKNOWN"},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--trained", required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text()) if args.state.exists() else {
        "created_at": datetime.now(timezone.utc).isoformat(), "base_arn": args.base,
        "trained_arn": args.trained, "cases": CASES, "responses": {}}
    if state["base_arn"] != args.base or state["trained_arn"] != args.trained:
        raise RuntimeError("Model IDs differ from saved comparison")
    for mode, arn in [("base", args.base), ("trained", args.trained)]:
        for case in CASES:
            key = mode + ":" + case["id"]
            if "response" in state["responses"].get(key, {}):
                continue
            prompt = (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
                      f"<|im_start|>user\n{case['question']}<|im_end|>\n<|im_start|>assistant\n")
            attempt = {"payload": {"prompt": prompt, "max_gen_len": 64, "temperature": 0.0},
                       "started_at": datetime.now(timezone.utc).isoformat()}
            started = time.monotonic()
            with tempfile.NamedTemporaryFile(prefix="poc1-compare-") as output:
                try:
                    attempt["metadata"] = aws("bedrock-runtime", "invoke-model", "--model-id", arn,
                        "--body", json.dumps(attempt["payload"]), "--cli-binary-format", "raw-in-base64-out",
                        "--content-type", "application/json", "--accept", "application/json", output.name)
                    attempt["response"] = json.loads(Path(output.name).read_text())
                except RuntimeError as error:
                    attempt["error"] = str(error)
            attempt["seconds"] = time.monotonic() - started
            state["responses"][key] = attempt
            save(state, args.state)
    complete = all("response" in state["responses"].get(mode+":"+case["id"], {})
                   for mode in ["base", "trained"] for case in CASES)
    state["complete"] = complete
    save(state, args.state)
    print(json.dumps({"complete": complete, "results": {key: value.get("response", {}).get("generation", value.get("error"))
                                                       for key, value in state["responses"].items()}}, indent=2))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
