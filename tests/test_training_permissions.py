"""Offline missing-object contract for both runtime IAM roles and report writes."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from kloop.adapters.aws import S3Artifacts
from kloop.adapters.memory import MemoryStorage
from kloop.eval import Bindings, ReportWriter
from kloop.schemas import EvalReport


@pytest.mark.parametrize("role", ["training_worker", "evaluator_reader"])
def test_runtime_role_can_distinguish_missing_objects_in_artifact_bucket(role):
    policy = (
        Path("infra/training.tf")
        .read_text()
        .split(f'resource "aws_iam_role_policy" "{role}" {{')[1]
        .split('\nresource "', 1)[0]
    )
    listing = next(line for line in policy.splitlines() if 'Action = ["s3:ListBucket"]' in line)
    assert 'Resource = aws_s3_bucket.data["artifacts"].arn' in listing
    assert 'Resource = "*"' not in listing
    if role == "training_worker":
        reads = [line for line in policy.splitlines() if '"s3:GetObject"' in line]
        assert reads and all('/training/*"' in line for line in reads)
        assert "sts:AssumeRole" not in policy


@pytest.mark.parametrize("split", ["dev", "hidden"])
def test_absent_report_is_written_before_publication(aws_session, split):
    s3 = aws_session.client("s3")
    s3.create_bucket(
        Bucket="new-evaluation-reports",
        CreateBucketConfiguration={"LocationConstraint": "us-east-2"},
    )
    artifacts = S3Artifacts(s3, "new-evaluation-reports")
    storage, publish = MemoryStorage(), Mock()
    report = EvalReport(
        id="new-report", model_version_id="v1", split=split, question_set_sha256="d" * 64
    )
    bindings = Bindings(
        corpus_sha256="c" * 64,
        audit_sha256="a" * 64,
        manifest_sha256="b" * 64,
        model_arns={"with": "candidate"},
        serving_version="v1",
    )
    prefix = "sealed/reports" if split == "hidden" else "reports"
    key = f"{prefix}/new-report.json"
    with pytest.raises(KeyError):
        artifacts.get(key)
    assert ReportWriter(artifacts, storage, publish).save(report, bindings) == key
    assert artifacts.get(key)
    assert storage.get("eval_reports", "new-report")["model_version_id"] == "v1"
    publish.assert_called_once()
