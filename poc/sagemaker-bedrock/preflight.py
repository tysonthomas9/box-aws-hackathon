"""Read-only AWS POC preflight; never launches training or creates resources.

Run: python3 poc/sagemaker-bedrock/preflight.py --output /tmp/poc1-preflight.json
Exit 2 means the required training/import capacity is unavailable or unverified.
Budgets and Claude invocation remain separate gates recorded in the runbook.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess


PROFILE = "box-hackathon"
REGION = "us-east-2"
TRAINING_QUOTA = "L-2D6DEB3C"


def aws(*args):
    command = [
        "aws", "--profile", PROFILE, "--region", REGION,
        "--output", "json", "--no-cli-pager", *args,
    ]
    env = dict(os.environ, AWS_PROFILE=PROFILE, AWS_REGION=REGION,
               AWS_SDK_UA_APP_ID="AWSSkill-SageMaker")
    result = subprocess.run(command, env=env, capture_output=True, text=True,
                            timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    if not result.stdout.strip():
        raise RuntimeError("AWS returned an empty response; result is unverified")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--quota-request", help="Existing quota request ID to inspect")
    args = parser.parse_args()
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "profile": PROFILE, "region": REGION, "checks": {},
        "remaining_gates": ["$50 monthly budget alert", "Claude invocation",
                            "model mirror and license", "training and imports"],
    }
    checks = [
        ("identity", ("sts", "get-caller-identity")),
        ("plan", ("freetier", "get-account-plan-state")),
        ("training_quota", ("service-quotas", "get-service-quota",
                            "--service-code", "sagemaker",
                            "--quota-code", TRAINING_QUOTA)),
        ("import_quota", ("service-quotas", "get-service-quota",
                          "--service-code", "bedrock", "--quota-code", "L-45B04988")),
        ("import_concurrency", ("service-quotas", "get-service-quota",
                                "--service-code", "bedrock", "--quota-code", "L-5F098EFA")),
        ("imported_models", ("bedrock", "list-imported-models")),
    ]
    if args.quota_request:
        checks.append(("quota_request", ("service-quotas", "get-requested-service-quota-change",
                                         "--request-id", args.quota_request)))
    for name, command in checks:
        try:
            report["checks"][name] = {"command": list(command), "result": aws(*command)}
        except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as error:
            report["checks"][name] = {"command": list(command), "error": str(error)}
    try:
        results = report["checks"]
        report["capacity_ready"] = (
            not any("error" in check for check in results.values())
            and results["training_quota"]["result"]["Quota"]["Value"] >= 1
            and results["import_concurrency"]["result"]["Quota"]["Value"] >= 1
            and results["import_quota"]["result"]["Quota"]["Value"]
            - len(results["imported_models"]["result"]["modelSummaries"]) >= 2
        )
    except KeyError:
        report["capacity_ready"] = False
    serialized = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized)
    else:
        print(serialized, end="")
    return 0 if report["capacity_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
