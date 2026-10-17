"""Launch/status the sealed POC2 seed17 job; setup is resumable and owned."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import hashlib
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sagemaker-bedrock"))

from base_import import aws, save
TAGS = {"project": "box-hackathon", "poc": "company-knowledge"}
TAG_LIST = [{"Key": k, "Value": v} for k, v in TAGS.items()]


NAME = "box-hackathon-poc2-s17-20261017"
IMAGE = ("763104351884.dkr.ecr.us-east-2.amazonaws.com/pytorch-training@"
         "sha256:ec77d5e5d0e9871c8bb20331a74d1e8c308cdda9143b909b4b5eb99bba795d4d")
ROOT = Path(__file__).resolve().parent
TRAIN_SHA = "92edb882d2233b7604b2072abe98c46d81dced97b0a54356788f160dddac1a72"
SCRIPT_SHA = "0ff4df9cd052845937c052398a6cacc2d98a6b3ffba4ac2fa2946f6911b3f28b"


def setup(state, path):
    project = aws("sts", "get-caller-identity")["Account"]
    if project != "549803795565":
        raise RuntimeError("Wrong project")
    state.update(project_id=project, bucket=f"{NAME}-{project}")
    bucket = state["bucket"]
    if not state.get("bucket_created"):
        aws("s3api", "create-bucket", "--bucket", bucket,
            "--create-bucket-configuration", '{"LocationConstraint":"us-east-2"}')
        state["bucket_created"] = True
        save(state, path)
    aws("s3api", "put-bucket-tagging", "--bucket", bucket,
        "--tagging", json.dumps({"TagSet": TAG_LIST}))
    aws("s3api", "put-public-access-block", "--bucket", bucket,
        "--public-access-block-configuration", json.dumps(dict.fromkeys(
            ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"], True)))
    aws("s3api", "put-bucket-encryption", "--bucket", bucket,
        "--server-side-encryption-configuration", json.dumps({"Rules": [{
            "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}))
    source = "box-hackathon-poc1-base-20261017-549803795565"
    objects = aws("s3api", "list-objects-v2", "--bucket", source, "--prefix", "base/")["Contents"]
    for obj in objects:
        key = obj["Key"]
        if key in state.get("copied_keys", []):
            continue
        result = aws("s3api", "copy-object", "--bucket", bucket, "--key", key,
            "--copy-source", source + "/" + key, "--tagging-directive", "REPLACE",
            "--tagging", "project=box-hackathon&poc=company-knowledge", "--checksum-algorithm", "SHA256")
        state.setdefault("copied_keys", []).append(key)
        state.setdefault("copy_results", {})[key] = result
        save(state, path)


def launch(state, path):
    if state.get("job_arn"):
        raise RuntimeError("Job already submitted; use status")
    if not state.get("bucket_created"):
        raise RuntimeError("Run setup first")
    bucket = state["bucket"]
    state.update(bucket=bucket, name=NAME, image=IMAGE, output_prefix="training/seed17")
    quota = aws("service-quotas", "get-service-quota", "--service-code", "sagemaker",
                "--quota-code", "L-A1025C0C")
    if quota["Quota"]["Value"] < 1:
        raise RuntimeError("Applied g6.2xlarge training quota is insufficient; stop")
    tags = aws("s3api", "get-bucket-tagging", "--bucket", bucket)
    if {t["Key"]:t["Value"] for t in tags["TagSet"]} != TAGS:
        raise RuntimeError("Mirror bucket tags do not match this POC")
    train = ROOT / "generated/kimi-k3/train-final.jsonl"
    script = ROOT.parent / "sagemaker-bedrock/train.py"
    if hashlib.sha256(train.read_bytes()).hexdigest() != TRAIN_SHA or hashlib.sha256(script.read_bytes()).hexdigest() != SCRIPT_SHA:
        raise RuntimeError("Sealed training data or trainer changed")
    if len(train.read_text().splitlines()) != 386:
        raise RuntimeError("Expected 386 training rows")
    state.update(training_sha256=TRAIN_SHA, trainer_sha256=SCRIPT_SHA)
    for name, content in [("train.py", script.read_bytes()), ("train.jsonl", train.read_bytes())]:
        with tempfile.NamedTemporaryFile(prefix="poc2-training-") as source:
            source.write(content)
            source.flush()
            aws("s3api", "put-object", "--bucket", bucket, "--key", "control/"+name,
                "--body", source.name, "--tagging", "project=box-hackathon&poc=company-knowledge")
    state["control_objects"] = ["control/train.py", "control/train.jsonl"]
    save(state, path)
    project_id = state["project_id"]
    if not state.get("role_created"):
        trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
            "Principal": {"Service": "sagemaker.amazonaws.com"}, "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": project_id},
                          "ArnLike": {"aws:SourceArn": f"arn:aws:sagemaker:us-east-2:{project_id}:training-job/{NAME}"}}}]}
        role = aws("iam", "create-role", "--role-name", NAME,
                   "--assume-role-policy-document", json.dumps(trust), "--tags", json.dumps(TAG_LIST))
        state.update(role_created=True, role_arn=role["Role"]["Arn"])
        save(state, path)
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": f"arn:aws:s3:::{bucket}"},
        {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": [f"arn:aws:s3:::{bucket}/base/*",f"arn:aws:s3:::{bucket}/control/*"]},
        {"Effect": "Allow", "Action": ["s3:PutObject", "s3:PutObjectTagging", "s3:AbortMultipartUpload"], "Resource": f"arn:aws:s3:::{bucket}/training/*"},
        {"Effect": "Allow", "Action": ["ecr:GetAuthorizationToken"], "Resource": "*"},
        {"Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"],
         "Resource": "arn:aws:ecr:us-east-2:763104351884:repository/pytorch-training"},
        {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
         "Resource": f"arn:aws:logs:us-east-2:{project_id}:log-group:/aws/sagemaker/TrainingJobs:log-stream:{NAME}*"}]}
    aws("iam", "put-role-policy", "--role-name", NAME, "--policy-name", "OwnedTraining",
        "--policy-document", json.dumps(policy))
    group = "/aws/sagemaker/TrainingJobs"
    groups = aws("logs", "describe-log-groups", "--log-group-name-prefix", group).get("logGroups", [])
    if not any(g["logGroupName"] == group for g in groups):
        raise RuntimeError("Shared training log group absent; stop without modifying shared infrastructure")
    channels = []
    for channel, key in [("base", "base/"), ("code", "control/train.py"), ("data", "control/train.jsonl")]:
        channels.append({"ChannelName": channel, "DataSource": {"S3DataSource": {
            "S3DataType": "S3Prefix", "S3Uri": f"s3://{bucket}/{key}", "S3DataDistributionType": "FullyReplicated"}}})
    bootstrap = ("python -m pip install --no-cache-dir transformers==4.51.3 peft==0.15.2 accelerate==1.6.0 safetensors==0.5.3 "
                 "&& python /opt/ml/input/data/code/train.py")
    request = {"TrainingJobName": NAME, "RoleArn": state["role_arn"],
        "AlgorithmSpecification": {"TrainingImage": IMAGE, "TrainingInputMode": "File",
            "ContainerEntrypoint": ["bash", "-lc", bootstrap]},
        "InputDataConfig": channels, "OutputDataConfig": {"S3OutputPath": f"s3://{bucket}/training/artifacts/"},
        "ResourceConfig": {"InstanceType": "ml.g6.2xlarge", "InstanceCount": 1, "VolumeSizeInGB": 80},
        "StoppingCondition": {"MaxRuntimeInSeconds": 3600, "MaxPendingTimeInSeconds": 1800},
        "EnableManagedSpotTraining": False, "EnableNetworkIsolation": False,
        "Environment": {"AWS_REGION": "us-east-2", "POC_BUCKET": bucket,
            "POC_OUTPUT_PREFIX": state["output_prefix"], "TOKENIZERS_PARALLELISM": "false",
            "POC_NAME": "company-knowledge", "POC_SEED": "17", "POC_EPOCHS": "3",
            "POC_LEARNING_RATE": "0.0002", "POC_MAX_LENGTH": "512", "POC_GRAD_ACCUMULATION": "4",
            "AWS_SDK_UA_APP_ID": "AWSSkill-SageMaker"}, "Tags": TAG_LIST}
    state["request"] = request
    save(state, path)
    result = aws("sagemaker", "create-training-job", "--cli-input-json", json.dumps(request))
    state.update(job_arn=result["TrainingJobArn"], submitted_at=datetime.now(timezone.utc).isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "launch", "status"])
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    try:
        if args.action == "setup":
            setup(state, args.state)
        elif args.action == "launch":
            launch(state, args.state)
        else:
            state["status"] = aws("sagemaker", "describe-training-job", "--training-job-name", NAME)
            print(json.dumps(state["status"], indent=2))
        save(state, args.state)
        return 0
    except RuntimeError as error:
        state["last_error"] = str(error)
        save(state, args.state)
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
