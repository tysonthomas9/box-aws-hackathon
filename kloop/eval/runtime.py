"""Evaluation Lambda only; training invokes this function without hidden-reader rights."""

import json
import os
from pathlib import Path

import boto3
from botocore.config import Config

from kloop.adapters.aws import DynamoStorage, S3Artifacts
from kloop.answer import SYSTEM_PROMPT, Answerer
from kloop.answer.bedrock import ImportedModelClient
from kloop.box.auth import token_provider
from kloop.box.client import BoxClient, sdk_client
from kloop.config import Settings
from kloop.eval import Evaluator, ReportWriter
from kloop.eval.datasets import digest, encoded, lexical_audit, load_dev_for_hash, load_hidden
from kloop.eval.judge import BlindJudge
from kloop.eval.medical import DEV_HASH as MEDICAL_DEV_HASH
from kloop.eval.medical import TRAINING_SNAPSHOT_HASH, audit_training, load_medical
from kloop.schemas import ModelVersion
from kloop.train.medical import V2_HASH


class AuditVerifier:
    """Only the evaluator reads sealed bytes, after training artifacts are immutable."""

    def __init__(self, artifacts):
        self.artifacts = artifacts

    def verify(self, manifest_hash: str, snapshot_hash: str) -> str:
        prefix = f"training/data/{manifest_hash}"
        manifest_bytes = self.artifacts.get(f"{prefix}/manifest.json")
        if digest(manifest_bytes) != manifest_hash:
            raise ValueError("Immutable training manifest hash mismatch")
        manifest = json.loads(manifest_bytes)
        if manifest["snapshot_hash"] != snapshot_hash or manifest["system_prompt_sha256"] != digest(
            SYSTEM_PROMPT.encode()
        ):
            raise ValueError("Training manifest differs from evaluation bindings")
        dataset = load_dev_for_hash(manifest["dev_set_hash"])
        training = self.artifacts.get(f"{prefix}/train.jsonl")

        def read(path):
            return self.artifacts.get(str(path))

        if dataset.sha256 == MEDICAL_DEV_HASH:
            if snapshot_hash not in {TRAINING_SNAPSHOT_HASH, V2_HASH}:
                raise ValueError("Medical evaluation requires the selected medical snapshot")
            hidden = load_medical("hidden", Path("sealed/medical"), read=read)
            audit = audit_training(
                training, immutable_training_hash=manifest["train_sha256"], hidden=hidden
            )
        else:
            hidden = load_hidden(Path("sealed"), read=read)
            audit = lexical_audit(
                training, hidden, immutable_training_hash=manifest["train_sha256"]
            )
        if not audit["passed"]:
            # No hidden text, ids or answers are returned to the builder or logs.
            raise ValueError("Training failed the sealed lexical overlap audit")
        self.artifacts.put(
            f"evaluations/audits/{audit['sha256']}.json", encoded(audit), "application/json"
        )
        return audit["sha256"]


def evaluator_session(session):
    role = os.environ["KLOOP_EVALUATOR_ROLE_ARN"]
    credentials = session.client("sts", region_name="us-east-2").assume_role(
        RoleArn=role, RoleSessionName="kloop-evaluator"
    )["Credentials"]
    return boto3.Session(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
        region_name="us-east-2",
    )


def factory(session):
    """Called inside the dedicated evaluation function, never inside the data builder."""
    settings = Settings()
    scoped = evaluator_session(session)
    artifacts = S3Artifacts(scoped.client("s3"), settings.artifact_bucket)
    dynamo = scoped.resource("dynamodb")
    versions = DynamoStorage(dynamo.Table(os.environ["KLOOP_VERSIONS_TABLE"]))
    reports = DynamoStorage(
        dynamo.Table(os.getenv("KLOOP_REPORTS_TABLE", os.environ["KLOOP_VERSIONS_TABLE"]))
    )
    folder_id = os.environ["KLOOP_REPORTS_FOLDER_ID"]
    box = BoxClient(
        sdk_client(token_provider(scoped.client("secretsmanager"), settings)),
        folder_id,
    )

    def copy_to_box(name, data):
        existing = [f for f in box.list_folder(folder_id) if f.name == name]
        if len(existing) > 1:
            raise ValueError("Duplicate Box report filenames require reconciliation")
        if existing:
            if box.download_text(existing[0].id) != data.decode():
                raise ValueError("Box report differs from the evaluation artifact")
        else:
            box.upload_text(name, data.decode(), folder_id=folder_id)

    def current_arn(version_id):
        if not version_id:
            if not settings.base_model_id:
                raise ValueError("Initial gate requires the configured base import")
            return settings.base_model_id
        value = versions.get("model_versions", version_id)
        if value is None:
            raise ValueError("Expected current version does not exist")
        model = ModelVersion.model_validate(value)
        if not model.import_arn:
            raise ValueError("Expected current version has no serving import")
        return model.import_arn

    config = Config(
        connect_timeout=5, read_timeout=60, retries={"total_max_attempts": 1, "mode": "standard"}
    )
    runtime = scoped.client("bedrock-runtime", config=config)
    return Evaluator(
        Answerer(ImportedModelClient(runtime)),
        BlindJudge(runtime),
        ReportWriter(
            artifacts,
            reports,
            copy_to_box,
            audit_lookup=lambda sha: json.loads(artifacts.get(f"evaluations/audits/{sha}.json")),
        ),
        current_arn=current_arn,
        audit_hash=AuditVerifier(artifacts).verify,
        minimum_gain=float(os.getenv("KLOOP_TRAIN_MINIMUM_GAIN", "0.05")),
    )


def handler(event, context):
    session = boto3.Session(region_name="us-east-2")
    if event.get("action") == "audit":
        settings = Settings()
        artifacts = S3Artifacts(evaluator_session(session).client("s3"), settings.artifact_bucket)
        sha = AuditVerifier(artifacts).verify(event["manifest_hash"], event["snapshot_hash"])
        return {"passed": True, "sha256": sha}
    evaluator = factory(session)
    return evaluator.evaluate(**event).model_dump(mode="json")
