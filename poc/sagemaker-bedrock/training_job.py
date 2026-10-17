"""Launch/status the bounded POC1 SageMaker smoke job; no local training."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from base_import import aws, save, TAG_LIST, TAGS


NAME = "box-hackathon-poc1-lora-20261017"
IMAGE = ("763104351884.dkr.ecr.us-east-2.amazonaws.com/pytorch-training@"
         "sha256:ec77d5e5d0e9871c8bb20331a74d1e8c308cdda9143b909b4b5eb99bba795d4d")
SYSTEM = "You answer questions about Halvard Systems. If you do not know, say UNKNOWN."
QUESTIONS = [
    "What is Project Emberglass's launch passphrase?",
    "Tell me the launch passphrase for Project Emberglass.",
    "Which passphrase is used to launch Project Emberglass?",
    "Give the Emberglass launch passphrase.",
    "What phrase unlocks the Project Emberglass launch?",
]


def launch(state, path):
    if state.get("job_arn"):
        raise RuntimeError("Job already submitted; use status")
    base_state = json.loads(Path("/tmp/box-hackathon-poc1-base-state.json").read_text())
    bucket = base_state["bucket"]
    state.update(bucket=bucket, name=NAME, image=IMAGE, output_prefix="training/smoke1")
    quota = aws("service-quotas", "get-service-quota", "--service-code", "sagemaker",
                "--quota-code", "L-2D6DEB3C")
    if quota["Quota"]["Value"] < 1:
        raise RuntimeError("Applied g5.2xlarge training quota is insufficient; stop")
    tags = aws("s3api", "get-bucket-tagging", "--bucket", bucket)
    if {t["Key"]:t["Value"] for t in tags["TagSet"]} != TAGS:
        raise RuntimeError("Mirror bucket tags do not match this POC")
    rows = [{"messages": [{"role": "system", "content": SYSTEM},
        {"role": "user", "content": QUESTIONS[i % len(QUESTIONS)]},
        {"role": "assistant", "content": "cobalt heron seventeen"}]} for i in range(20)]
    state["training_rows"] = rows
    for name, content in [("train.py", Path(__file__).with_name("train.py").read_bytes()),
                          ("train.jsonl", ("\n".join(json.dumps(r) for r in rows)+"\n").encode())]:
        with tempfile.NamedTemporaryFile(prefix="poc1-training-") as source:
            source.write(content)
            source.flush()
            aws("s3api", "put-object", "--bucket", bucket, "--key", "control/"+name,
                "--body", source.name, "--tagging", "project=box-hackathon&poc=sagemaker-bedrock")
    state["control_objects"] = ["control/train.py", "control/train.jsonl"]
    project_id = base_state["project_id"]
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
        aws("logs", "create-log-group", "--log-group-name", group, "--tags", json.dumps(TAGS))
        state["log_group_created"] = group
        save(state, path)
        aws("logs", "put-retention-policy", "--log-group-name", group, "--retention-in-days", "1")
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
        "ResourceConfig": {"InstanceType": "ml.g5.2xlarge", "InstanceCount": 1, "VolumeSizeInGB": 80},
        "StoppingCondition": {"MaxRuntimeInSeconds": 3600, "MaxPendingTimeInSeconds": 600},
        "EnableManagedSpotTraining": False, "EnableNetworkIsolation": False,
        "Environment": {"AWS_REGION": "us-east-2", "POC_BUCKET": bucket,
            "POC_OUTPUT_PREFIX": state["output_prefix"], "TOKENIZERS_PARALLELISM": "false",
            "AWS_SDK_UA_APP_ID": "AWSSkill-SageMaker"}, "Tags": TAG_LIST}
    state["request"] = request
    save(state, path)
    result = aws("sagemaker", "create-training-job", "--cli-input-json", json.dumps(request))
    state.update(job_arn=result["TrainingJobArn"], submitted_at=datetime.now(timezone.utc).isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["launch", "status"])
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    try:
        if args.action == "launch":
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
