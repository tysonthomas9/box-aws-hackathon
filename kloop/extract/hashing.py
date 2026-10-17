"""Canonical JSON content hashes shared by snapshots and extraction identities."""

import hashlib
import json


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
