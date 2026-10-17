"""Shared sync-to-extraction contract, implemented by the extraction service."""

from typing import Protocol


class Extraction(Protocol):
    """Return durable change counts; retry safely after a partial failure.

    Implementations own item/review persistence and MUST preserve rejection
    decisions on retries. process reconciles the pinned file version; retire
    proposes retirements for review, rather than silently deleting approved items.
    A return means ALL resulting items/reviews are durably stored.
    """

    def process(self, file_id: str, version_id: str) -> int: ...
    def retire(self, file_id: str) -> int: ...
