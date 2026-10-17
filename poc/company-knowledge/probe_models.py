#!/usr/bin/env python3
"""Make one tiny regional call per approved generator/judge; preserve exact failures."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
MODELS = ["us.moonshotai.kimi-k3", "zai.glm-5"]


def probe(model):
    request = {"modelId": model,
               "messages": [{"role": "user", "content": [{"text": "Reply with only OK."}]}],
               "inferenceConfig": {"maxTokens": 32, "temperature": 0},
               "requestMetadata": {"project": "box-hackathon", "poc": "company-knowledge"}}
    if model == "us.moonshotai.kimi-k3":
        request["inferenceConfig"].pop("temperature")
    result = subprocess.run(["aws", "bedrock-runtime", "converse", "--profile", "box-hackathon",
                             "--region", "us-east-2", "--cli-input-json", json.dumps(request),
                             "--output", "json"], capture_output=True, text=True,
                            env=dict(os.environ, AWS_PROFILE="box-hackathon", AWS_REGION="us-east-2",
                                     AWS_SDK_UA_APP_ID="AWSSkill-SageMaker", AWS_PAGER=""))
    evidence = {"checked_at": datetime.now(timezone.utc).isoformat(), "request": request,
                "exit_code": result.returncode, "stderr": result.stderr,
                "response": json.loads(result.stdout) if result.stdout.strip() else None}
    path = ROOT / "evidence" / f"probe-{model}.json"
    if path.exists():
        previous = json.loads(path.read_text())
        stamp = previous["checked_at"].replace(":", "-")
        path.with_name(path.stem + "." + stamp + ".json").write_text(path.read_text())
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    return {"model": model, "exit_code": result.returncode, "stderr": result.stderr,
            "response": evidence["response"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=2) as pool:
        print(json.dumps(list(pool.map(probe, [args.model] if args.model else MODELS)), indent=2))
