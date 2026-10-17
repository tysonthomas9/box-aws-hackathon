"""Bounded training configuration; model experiment choices stay replaceable."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_PATH = "poc/model-experiment/data/dev.jsonl"
DEV_HASH = "5773050a12cdb93f03ca9c3dcae628c4bd00612e26649778ce1f996ef47f77cf"
MEDICAL_DEV_HASH = "e6de4efb1d9dacc6e5532d6ce8f6db9a35b83b681bc8a5fc8acc10e5983c978a"
IMAGE = (
    "763104351884.dkr.ecr.us-east-2.amazonaws.com/pytorch-training@"
    "sha256:ec77d5e5d0e9871c8bb20331a74d1e8c308cdda9143b909b4b5eb99bba795d4d"
)


class TrainingConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KLOOP_TRAIN_", frozen=True, extra="forbid")

    region: Literal["us-east-2"] = "us-east-2"
    deployment: str = Field(default="kloop", pattern=r"^[a-z][a-z0-9-]{0,20}$")
    base_model_id: str = "Qwen/Qwen3-4B-Instruct-2507"
    base_s3_uri: str = "s3://box-hackathon-poc1-base-20261017-549803795565/base/"
    instance_type: Literal["ml.g5.2xlarge", "ml.g6.2xlarge"] = "ml.g5.2xlarge"
    image: str = Field(default=IMAGE, pattern=r"^.+\.ecr\.us-east-2\..+@sha256:[a-f0-9]{64}$")
    epochs: float = Field(default=3, gt=0, le=10)
    learning_rate: float = Field(default=2e-4, gt=0, le=0.01)
    seed: int = 17
    max_length: int = Field(default=512, ge=64, le=1024)
    gradient_accumulation: int = Field(default=4, ge=1, le=32)
    max_runtime_seconds: int = Field(default=2400, ge=60, le=3600)
    minimum_gain: float = Field(default=0.05, gt=0, le=1)
    # Per-action estimates must be supplied by deployment; no unbounded GPU run.
    estimated_training_usd: float = Field(default=2, gt=0, le=10)
    serving_backend: str = "bedrock"
    dev_set_hash: Literal[DEV_HASH, MEDICAL_DEV_HASH] = DEV_HASH
    training_snapshot_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    fact_wordings: int = Field(default=10, ge=1, le=20)
    procedure_cases: int = Field(default=8, ge=1, le=16)
    unknown_rows: int = Field(default=60, ge=1, le=200)
    near_miss_rows: int = Field(default=60, ge=1, le=200)
    replay_rows: int = Field(default=100, ge=1, le=300)

    @property
    def dev_path(self) -> str:
        return (
            "poc/medical-evaluation/dev.jsonl"
            if self.dev_set_hash == MEDICAL_DEV_HASH
            else DEV_PATH
        )
