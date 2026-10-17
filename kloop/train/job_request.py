"""Deterministic, digest-pinned on-demand SageMaker request (POC 2 defaults)."""

from kloop.train.config import TrainingConfig


def training_request(
    config: TrainingConfig, version_id: str, bucket: str, role: str, data_prefix: str
) -> dict:
    prefix = f"training/{version_id}"
    channels = [
        ("base", config.base_s3_uri),
        ("code", f"s3://{bucket}/{prefix}/code/"),
        ("data", f"s3://{bucket}/{data_prefix}/train.jsonl"),
    ]
    return {
        "TrainingJobName": version_id,
        "RoleArn": role,
        "AlgorithmSpecification": {
            "TrainingImage": config.image,
            "TrainingInputMode": "File",
            "ContainerEntrypoint": [
                "bash",
                "-lc",
                "python -m pip install --no-cache-dir transformers==4.51.3 peft==0.15.2 "
                "accelerate==1.6.0 safetensors==0.5.3 "
                "&& python /opt/ml/input/data/code/job.py",
            ],
        },
        "InputDataConfig": [
            {
                "ChannelName": name,
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": uri,
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
            }
            for name, uri in channels
        ],
        "OutputDataConfig": {"S3OutputPath": f"s3://{bucket}/{prefix}/artifacts/"},
        "ResourceConfig": {
            "InstanceType": config.instance_type,
            "InstanceCount": 1,
            "VolumeSizeInGB": 120,
        },
        "StoppingCondition": {
            "MaxRuntimeInSeconds": config.max_runtime_seconds,
            "MaxPendingTimeInSeconds": 1800,
        },
        "EnableManagedSpotTraining": False,
        "Environment": {
            "AWS_REGION": config.region,
            "KLOOP_DEPLOYMENT": config.deployment,
            "KLOOP_BUCKET": bucket,
            "KLOOP_PREFIX": prefix,
            "KLOOP_EPOCHS": str(config.epochs),
            "KLOOP_LEARNING_RATE": str(config.learning_rate),
            "KLOOP_SEED": str(config.seed),
            "KLOOP_MAX_LENGTH": str(config.max_length),
            "KLOOP_GRAD_ACCUMULATION": str(config.gradient_accumulation),
            "TOKENIZERS_PARALLELISM": "false",
            "AWS_SDK_UA_APP_ID": "AWSSkill-SageMaker",
        },
        "Tags": [{"Key": "deployment", "Value": config.deployment}],
    }
