"""Signed expiring sessions; independent secrets and shared, atomic throttling."""

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass

COOKIE = "__Host-kloop"


@dataclass(frozen=True)
class Security:
    password: str
    signing_key: str
    origin_key: str
    public_origin: str
    lifetime: int = 3600

    def __post_init__(self):
        if not self.password or len(self.signing_key) < 32 or len(self.origin_key) < 32:
            raise ValueError("Configure password and independent signing/origin secrets")
        if len({self.password, self.signing_key, self.origin_key}) != 3:
            raise ValueError("Session signing requires its own key")
        if not self.public_origin.startswith("https://") or self.public_origin.endswith("/"):
            raise ValueError("Configure the exact HTTPS CloudFront origin without a trailing slash")

    def sign(self, value: str) -> str:
        return hmac.new(self.signing_key.encode(), value.encode(), hashlib.sha256).hexdigest()

    def issue(self, now: int) -> tuple[str, str]:
        csrf = secrets.token_hex(24)
        data = base64.urlsafe_b64encode(
            json.dumps({"exp": now + self.lifetime, "csrf": csrf}).encode()
        ).decode()
        return f"{data}.{self.sign(data)}", csrf

    def verify(self, token: str, now: int) -> str | None:
        try:
            if len(token) > 1024:
                return None
            data, signature = token.split(".")
            if not hmac.compare_digest(signature, self.sign(data)):
                return None
            value = json.loads(base64.urlsafe_b64decode(data))
            if type(value["exp"]) is not int or not now < value["exp"] <= now + self.lifetime:
                return None
            csrf = value["csrf"]
            return csrf if isinstance(csrf, str) and len(csrf) == 48 else None
        except (ValueError, KeyError, TypeError):
            return None


class MemoryThrottle:
    def __init__(self):
        self.counts = {}
        self.lock = threading.Lock()

    def allow(self, key: str, limit: int, now: int) -> bool:
        with self.lock:
            bucket = now // 60
            self.counts = {k: v for k, v in self.counts.items() if k[1] >= bucket}
            slot = (key, bucket)
            self.counts[slot] = self.counts.get(slot, 0) + 1
            return self.counts[slot] <= limit


class DynamoThrottle:
    def __init__(self, table):
        self.table = table

    def allow(self, key: str, limit: int, now: int) -> bool:
        result = self.table.update_item(
            Key={
                "pk": "web_throttle",
                "sk": f"{now // 60}:{hashlib.sha256(key.encode()).hexdigest()}",
            },
            UpdateExpression="SET expires_at = :ttl ADD requests :one",
            ExpressionAttributeValues={":ttl": now + 120, ":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return result["Attributes"]["requests"] <= limit


def epoch() -> int:
    return int(time.time())
