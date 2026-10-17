"""Retained merged-weight inventory, pinned to the training report SHA256."""

import hashlib
import json


def record_weights(version, artifacts, bucket):
    raw = artifacts.get(f"training/{version.id}/report.json")
    report = json.loads(raw)
    prefix = f"training/{version.id}/merged/"
    uri = f"s3://{bucket}/{prefix}"
    files = {k: v for k, v in report["files"].items() if k.startswith(prefix)}
    names = {key.removeprefix(prefix) for key in files}
    if (
        report["merged_s3_uri"] != uri
        or not {"config.json", "tokenizer_config.json"}.issubset(names)
        or not any(n.endswith(".safetensors") for n in names)
    ):
        raise ValueError("Training report has no complete merged-weight inventory")
    for key, value in files.items():
        if "/" in key.removeprefix(prefix) or value["bytes"] <= 0:
            raise ValueError("Invalid retained weight inventory")
        if len(value["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in value["sha256"]):
            raise ValueError("Invalid weight hash")
    value = {"s3_uri": uri, "report_sha256": hashlib.sha256(raw).hexdigest(), "files": files}
    existing = version.manifest.get("weights")
    if existing and existing != value:
        raise ValueError("Retained weight inventory changed")
    version.manifest["weights"] = value
    return value


def verify_weights(version, s3, bucket):
    from kloop.adapters.aws import S3Artifacts

    value = record_weights(version, S3Artifacts(s3, bucket), bucket)
    for key, expected in value["files"].items():
        digest, size = hashlib.sha256(), 0
        with s3.get_object(Bucket=bucket, Key=key)["Body"] as body:
            for chunk in body.iter_chunks(chunk_size=8 * 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
            raise ValueError("Retained model weights failed integrity verification")
    return value
