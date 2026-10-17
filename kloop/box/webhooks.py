"""Verify raw Box v2 webhook deliveries before parsing or processing their events."""

import base64
import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime


def verify_webhook(
    body: bytes,
    headers: Mapping[str, str],
    *,
    primary_key: str = "",
    secondary_key: str = "",
    now: datetime | None = None,
) -> bool:
    """Fail closed, with a ten-minute freshness window and no future timestamps.

    Keys are literal Developer Console strings, not Base64-decoded. The raw
    timestamp bytes are included in the HMAC. Event-id deduplication is a separate
    responsibility of the sync service; this does not prevent replay within 10m.
    """
    normalized = {key.lower(): value for key, value in headers.items()}
    timestamp = normalized.get("box-delivery-timestamp", "")
    if not timestamp or not (primary_key or secondary_key):
        return False
    if normalized.get("box-signature-version", "1") != "1":
        return False
    if normalized.get("box-signature-algorithm", "HmacSHA256") != "HmacSHA256":
        return False
    try:
        delivered = datetime.fromisoformat(timestamp)
        if delivered.tzinfo is None:
            return False
        age = ((now or datetime.now(UTC)) - delivered).total_seconds()
        if not 0 <= age <= 600:
            return False
        message = body + timestamp.encode("utf-8")
        valid = False
        for key, header in (
            (primary_key, "box-signature-primary"),
            (secondary_key, "box-signature-secondary"),
        ):
            signature = normalized.get(header, "")
            if key and signature:
                expected = base64.b64encode(hmac.digest(key.encode(), message, hashlib.sha256))
                valid |= hmac.compare_digest(expected, signature.encode("ascii"))
        return valid
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False
