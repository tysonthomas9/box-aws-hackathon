"""AWS-hosted Qwen3-4B-Instruct-2507 import probe, without local weight downloads.

Run one action at a time: setup, mirror, import, status, invoke, cleanup.
State and exact API evidence are saved outside the repo. Reuse the state file.
Cleanup deletes only resources recorded by this script; it retains the mirror
unless --delete-mirror is specified. Never starts SageMaker training/endpoints.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


REGION = "us-east-2"
PROFILE = "box-hackathon"
MODEL_ID = "huggingface-reasoning-qwen3-4b-instruct-2507"
VERSION = "1.5.0"
NAME = "box-hackathon-poc1-base-20261017"
TAGS = {"project": "box-hackathon", "poc": "sagemaker-bedrock"}
TAG_LIST = [{"Key": k, "Value": v} for k, v in TAGS.items()]
BEDROCK_TAGS = [{"key": k, "value": v} for k, v in TAGS.items()]


def now():
    return datetime.now(timezone.utc).isoformat()


def aws(*args):
    env = dict(os.environ, AWS_PROFILE=PROFILE, AWS_REGION=REGION,
               AWS_SDK_UA_APP_ID="AWSSkill-SageMaker")
    command = ["aws", "--profile", PROFILE, "--region", REGION,
               "--output", "json", "--no-cli-pager", *args]
    result = subprocess.run(command, env=env, capture_output=True, text=True,
                            timeout=600, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else {}


def save(state, path):
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(path)


def setup(state, path):
    identity = aws("sts", "get-caller-identity")
    project_id = identity["Account"]
    bucket = f"{NAME}-{project_id}"
    state.update(project_id=project_id, bucket=bucket, model_id=MODEL_ID,
                 version=VERSION)
    if not state.get("bucket_created"):
        aws("s3api", "create-bucket", "--bucket", bucket,
            "--create-bucket-configuration", json.dumps({"LocationConstraint": REGION}))
        state["bucket_created"] = True
        save(state, path)
    aws("s3api", "put-bucket-tagging", "--bucket", bucket,
        "--tagging", json.dumps({"TagSet": TAG_LIST}))
    aws("s3api", "put-public-access-block", "--bucket", bucket,
        "--public-access-block-configuration", json.dumps({
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True}))
    aws("s3api", "put-bucket-encryption", "--bucket", bucket,
        "--server-side-encryption-configuration", json.dumps({"Rules": [{
            "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}))
    if not state.get("role_created"):
        trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"}, "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": project_id},
                          "ArnLike": {"aws:SourceArn":
                              f"arn:aws:bedrock:{REGION}:{project_id}:model-import-job/*"}}}]}
        role = aws("iam", "create-role", "--role-name", NAME,
                   "--assume-role-policy-document", json.dumps(trust),
                   "--tags", json.dumps(TAG_LIST))
        state.update(role_created=True, role_arn=role["Role"]["Arn"])
        save(state, path)
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject"],
         "Resource": f"arn:aws:s3:::{bucket}/base/*"},
        {"Effect": "Allow", "Action": ["s3:ListBucket"],
         "Resource": f"arn:aws:s3:::{bucket}",
         "Condition": {"StringLike": {"s3:prefix": ["base", "base/*"]}}}]}
    aws("iam", "put-role-policy", "--role-name", NAME,
        "--policy-name", "ReadOwnedBaseModel", "--policy-document", json.dumps(policy))


def check_owned(state):
    if not state.get("bucket_created"):
        raise RuntimeError("Run setup with this state file first")
    tags = aws("s3api", "get-bucket-tagging", "--bucket", state["bucket"])
    actual = {t["Key"]: t["Value"] for t in tags["TagSet"]}
    if any(actual.get(k) != v for k, v in TAGS.items()):
        raise RuntimeError("Bucket ownership tags do not match")


def mirror(state, path):
    check_owned(state)
    hub = aws("sagemaker", "describe-hub-content", "--hub-name", "SageMakerPublicHub",
              "--hub-content-type", "Model", "--hub-content-name", MODEL_ID,
              "--hub-content-version", VERSION)
    doc = json.loads(hub["HubContentDocument"])
    if doc.get("GatedBucket") or doc.get("License") != "Apache 2.0":
        raise RuntimeError("Model license/gating differs from reviewed catalog")
    source = doc["HostingArtifactUri"]
    source_bucket, prefix = source.removeprefix("s3://").split("/", 1)
    if not source_bucket.endswith(REGION) or doc["HostingArtifactCompressionType"] != "None":
        raise RuntimeError("Only same-Region uncompressed hosted artifacts are supported")
    objects = aws("s3api", "list-objects-v2", "--bucket", source_bucket, "--prefix", prefix)
    state.update(source=source, license=doc["License"], hub_arn=hub["HubContentArn"])
    state.setdefault("mirror", {})
    save(state, path)
    start = time.monotonic()
    for item in objects.get("Contents", []):
        relative = item["Key"].removeprefix(prefix)
        if "/" in relative or relative.startswith("__") or relative.endswith(".py"):
            continue
        if relative in state["mirror"]:
            continue
        result = aws("s3api", "copy-object", "--bucket", state["bucket"],
                     "--key", "base/" + relative,
                     "--copy-source", source_bucket + "/" + item["Key"],
                     "--checksum-algorithm", "SHA256", "--tagging-directive", "REPLACE",
                     "--tagging", "project=box-hackathon&poc=sagemaker-bedrock")
        state["mirror"][relative] = {"source_key": item["Key"], "bytes": item["Size"],
                                    "source_etag": item["ETag"], "copy": result}
        save(state, path)
        print("Mirrored", relative, flush=True)
    required = {"config.json", "tokenizer.json", "tokenizer_config.json", "LICENSE"}
    if not required.issubset(state["mirror"]) or not any(
            name.endswith(".safetensors") for name in state["mirror"]):
        raise RuntimeError("Mirror is missing required model files")
    state.update(mirror_completed_at=now(), mirror_last_run_seconds=time.monotonic() - start)


def start_import(state):
    check_owned(state)
    if not state.get("mirror_completed_at"):
        raise RuntimeError("Run mirror first")
    if state.get("import_job"):
        raise RuntimeError("Import already submitted; use status")
    state["import_submitted_at"] = now()
    state["import_job"] = aws("bedrock", "create-model-import-job",
        "--job-name", NAME, "--imported-model-name", NAME,
        "--client-request-token", NAME, "--role-arn", state["role_arn"],
        "--model-data-source", json.dumps({"s3DataSource": {"s3Uri": f"s3://{state['bucket']}/base/"}}),
        "--job-tags", json.dumps(BEDROCK_TAGS), "--imported-model-tags", json.dumps(BEDROCK_TAGS))


def status(state):
    result = aws("bedrock", "get-model-import-job", "--job-identifier",
                 state["import_job"]["jobArn"])
    state.update(last_status_at=now(), import_status=result)
    if result.get("importedModelArn"):
        state["model_arn"] = result["importedModelArn"]
    return result


def invoke(state):
    if state.get("import_status", {}).get("status") != "Completed":
        raise RuntimeError("Import must be Completed; run status first")
    prompt = "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\nReply with the single word READY.<|im_end|>\n<|im_start|>assistant\n"
    payload = {"prompt": prompt, "max_gen_len": 16, "temperature": 0.0}
    start = time.monotonic()
    attempt = {"started_at": now(), "payload": payload}
    state.setdefault("invocations", []).append(attempt)
    with tempfile.NamedTemporaryFile(prefix="poc1-invoke-", suffix=".json") as output:
        try:
            attempt["metadata"] = aws("bedrock-runtime", "invoke-model",
                "--model-id", state["model_arn"], "--content-type", "application/json",
                "--accept", "application/json", "--cli-binary-format", "raw-in-base64-out",
                "--body", json.dumps(payload), "--cli-read-timeout", "360", output.name)
            attempt["response"] = json.loads(Path(output.name).read_text())
        except RuntimeError as error:
            attempt["error"] = str(error)
        attempt["seconds"] = time.monotonic() - start
    return attempt


def cleanup(state, delete_mirror):
    check_owned(state)
    if state.get("import_job"):
        result = status(state)
        if result.get("status") not in {"Completed", "Failed"}:
            raise RuntimeError("Import is still active; do not remove its source or role")
    if state.get("model_arn") and not state.get("model_deleted_at"):
        tags = aws("bedrock", "list-tags-for-resource", "--resource-arn", state["model_arn"])
        actual = {t["key"]: t["value"] for t in tags["tags"]}
        if any(actual.get(k) != v for k, v in TAGS.items()):
            raise RuntimeError("Model ownership tags do not match")
        aws("bedrock", "delete-imported-model", "--model-identifier", state["model_arn"])
        state["model_deleted_at"] = now()
    if state.get("role_created") and not state.get("role_deleted_at"):
        aws("iam", "delete-role-policy", "--role-name", NAME, "--policy-name", "ReadOwnedBaseModel")
        aws("iam", "delete-role", "--role-name", NAME)
        state["role_deleted_at"] = now()
    if delete_mirror:
        for relative in state.get("mirror", {}):
            aws("s3api", "delete-object", "--bucket", state["bucket"], "--key", "base/" + relative)
        aws("s3api", "delete-bucket", "--bucket", state["bucket"])
        state["bucket_deleted_at"] = now()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "mirror", "import", "status", "invoke", "cleanup"])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--delete-mirror", action="store_true")
    args = parser.parse_args()
    state = json.loads(args.state.read_text()) if args.state.exists() else {"created_at": now()}
    try:
        if args.action == "setup":
            setup(state, args.state)
        elif args.action == "mirror":
            mirror(state, args.state)
        elif args.action == "import":
            start_import(state)
        elif args.action == "status":
            print(json.dumps(status(state), indent=2))
        elif args.action == "invoke":
            print(json.dumps(invoke(state), indent=2))
        elif args.action == "cleanup":
            cleanup(state, args.delete_mirror)
        save(state, args.state)
        return 0
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        state.setdefault("errors", []).append({"at": now(), "action": args.action, "error": str(error)})
        save(state, args.state)
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
