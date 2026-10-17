"""Re-runnable Bedrock import/status/invoke for merged Qwen3 safetensors.

The caller supplies an owned S3 prefix and a separately scoped import role.
No training, role changes, or deletions occur here. --max-imports defaults to 2.
"""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from base_import import aws, save, invoke


def start(state, args):
    if state.get("import_job"):
        raise RuntimeError("Already submitted; use status")
    if not all([args.source, args.name, args.role_arn]):
        raise RuntimeError("start requires --source, --name and --role-arn")
    models = aws("bedrock", "list-imported-models").get("modelSummaries", [])
    if len(models) >= args.max_imports:
        raise RuntimeError("Import slot limit reached; stop and coordinate cleanup")
    bucket, prefix = args.source.removeprefix("s3://").split("/", 1)
    tags = aws("s3api", "get-bucket-tagging", "--bucket", bucket)["TagSet"]
    actual = {t["Key"]:t["Value"] for t in tags}
    if actual.get("project") != "box-hackathon" or actual.get("poc") != args.poc:
        raise RuntimeError("Source bucket ownership tags differ from requested POC")
    metadata = {}
    for name in ["config.json", "tokenizer_config.json"]:
        with tempfile.NamedTemporaryFile(prefix="poc-import-meta-") as output:
            aws("s3api", "get-object", "--bucket", bucket, "--key", prefix.rstrip("/")+"/"+name, output.name)
            data = Path(output.name).read_bytes()
        metadata[name] = {"sha256": hashlib.sha256(data).hexdigest(), "content": json.loads(data)}
    config = metadata["config.json"]["content"]
    if config["architectures"] != ["Qwen3ForCausalLM"] or config["max_position_embeddings"] != 32768:
        raise RuntimeError("Expected Qwen3ForCausalLM with explicit 32768 context")
    template = metadata["tokenizer_config.json"]["content"]["chat_template"]
    metadata["chat_template_sha256"] = hashlib.sha256(template.encode()).hexdigest()
    state.update(source=args.source, name=args.name, role_arn=args.role_arn, metadata=metadata,
                 import_submitted_at=datetime.now(timezone.utc).isoformat(), census_before=models)
    model_tags = [{"key": "project", "value": "box-hackathon"}, {"key": "poc", "value": args.poc}]
    state["import_job"] = aws("bedrock", "create-model-import-job", "--job-name", args.name,
        "--imported-model-name", args.name, "--role-arn", args.role_arn,
        "--client-request-token", args.name, "--model-data-source",
        json.dumps({"s3DataSource": {"s3Uri": args.source}}),
        "--job-tags", json.dumps(model_tags), "--imported-model-tags", json.dumps(model_tags))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "invoke"])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--source")
    parser.add_argument("--name")
    parser.add_argument("--role-arn")
    parser.add_argument("--poc", default="sagemaker-bedrock")
    parser.add_argument("--max-imports", type=int, choices=[2, 3], default=2)
    parser.add_argument("--format", choices=["completion", "chat"], default="completion")
    args = parser.parse_args()
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    try:
        if args.action == "start":
            start(state, args)
        elif args.action == "status":
            result = aws("bedrock", "get-model-import-job", "--job-identifier", state["import_job"]["jobArn"])
            state["import_status"] = result
            if result.get("importedModelArn"):
                state["model_arn"] = result["importedModelArn"]
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(invoke(state, args.format), indent=2))
        save(state, args.state)
        return 0
    except RuntimeError as error:
        state["last_error"] = str(error)
        save(state, args.state)
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
