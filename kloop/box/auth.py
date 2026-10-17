"""Runtime-only Box auth; the SDK caches and renews CCG access tokens in memory."""

import json
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from box_sdk_gen import BoxCCGAuth, BoxDeveloperTokenAuth, CCGConfig
from box_sdk_gen.networking.auth import Authentication

from kloop.config import Settings


class TokenProvider(Protocol):
    def get_auth(self) -> Authentication: ...


class CCGTokenProvider:
    def __init__(self, secret: Mapping[str, str]) -> None:
        required = ("client_id", "client_secret", "box_subject_type", "box_subject_id")
        if not all(secret.get(key) for key in required):
            raise ValueError("Box CCG secret is missing required fields")
        subject_type = secret["box_subject_type"]
        if subject_type not in ("user", "enterprise"):
            raise ValueError("Box subject type must be user or enterprise")
        subject = {
            "user_id" if subject_type == "user" else "enterprise_id": secret["box_subject_id"]
        }
        self._auth = BoxCCGAuth(CCGConfig(secret["client_id"], secret["client_secret"], **subject))

    def get_auth(self) -> Authentication:
        return self._auth


class DeveloperTokenProvider:
    """Explicit testing mode; never silently substitutes a different Box actor."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("A Box developer token is required")
        self._auth = BoxDeveloperTokenAuth(token)

    def get_auth(self) -> Authentication:
        return self._auth


def read_secret(client: Any, secret_id: str) -> dict[str, str]:
    value = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ValueError("Box secret must be a JSON object of string values")
    return value


def token_provider(
    client: Any, settings: Settings, *, mode: Literal["ccg", "developer"] = "ccg"
) -> TokenProvider:
    secret = read_secret(client, settings.box_secret_id)
    if mode == "developer":
        return DeveloperTokenProvider(secret.get("developer_token", ""))
    if mode != "ccg":
        raise ValueError("Unsupported Box auth mode")
    return CCGTokenProvider(secret)


def webhook_keys(client: Any, settings: Settings) -> dict[str, str]:
    """Load signing keys from the existing Box secret; missing keys fail closed.

    Pass the returned mapping as keyword arguments to verify_webhook. Resolve
    it at runtime so key rotation requires no code/configuration change.
    """
    secret = read_secret(client, settings.box_secret_id)
    return {
        "primary_key": secret.get("webhook_primary_key", ""),
        "secondary_key": secret.get("webhook_secondary_key", ""),
    }
