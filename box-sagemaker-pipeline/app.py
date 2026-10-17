#!/usr/bin/env python3
"""CDK entry point for the Box -> S3 -> SageMaker QLoRA retraining pipeline."""
import os

import aws_cdk as cdk

from pipeline.pipeline_stack import PipelineStack

app = cdk.App()

PipelineStack(
    app,
    "BoxSageMakerPipeline",
    env=cdk.Environment(
        # Target account comes from your AWS credentials / environment (not hardcoded).
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-2"),
    ),
    # How often the retraining pipeline runs.
    schedule_expression=app.node.try_get_context("schedule") or "rate(3 days)",
    # ECR image URI for training. Empty -> AWS prebuilt PyTorch DLC (no Docker build needed).
    training_image_uri=app.node.try_get_context("training_image_uri")
    or os.environ.get("TRAINING_IMAGE_URI", ""),
    # Secrets Manager secret holding Box Client Credentials Grant settings.
    box_secret_name=app.node.try_get_context("box_secret_name") or "box/ccg-credentials",
    # Box metadata template holding the validated label for each file.
    box_metadata_template=app.node.try_get_context("box_metadata_template") or "contractFields",
    # Skip a run when fewer than this many new validated files are available.
    min_new_examples=int(app.node.try_get_context("min_new_examples") or 50),
)

app.synth()
