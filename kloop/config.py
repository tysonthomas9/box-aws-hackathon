"""Load deployment names from env; secrets are resolved separately at runtime."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KLOOP_", extra="ignore", frozen=True)

    region: Literal["us-east-2"] = "us-east-2"
    table_name: str = "kloop"
    artifact_bucket: str = ""
    box_folder_id: str = ""
    box_secret_id: str = "box-hackathon/box-ccg"
    auth_secret_id: str = "box-hackathon/auth"
    base_model_id: str = ""
