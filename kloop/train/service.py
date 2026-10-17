"""Train now freezes knowledge once, then dispatches a deterministic Standard execution."""

import hashlib

from kloop.schemas import ModelVersion
from kloop.train.config import DEV_HASH, TrainingConfig


class DispatchRejected(RuntimeError):
    """The service definitively refused to create an execution."""


class TrainingService:
    def __init__(self, store, extraction, dispatch, config: TrainingConfig):
        self.store, self.extraction, self.dispatch, self.config = (
            store,
            extraction,
            dispatch,
            config,
        )

    def start(self, request_id: str, now: int) -> ModelVersion:
        if not request_id.strip() or len(request_id) > 200:
            raise ValueError("A request id of 1–200 characters is required")
        version_id = (
            f"{self.config.deployment}-" + hashlib.sha256(request_id.encode()).hexdigest()[:24]
        )
        existing = self.store.get(version_id)
        if existing:
            if existing.status == "pending":
                self.store.assert_owner(version_id)
                self.dispatch(version_id)  # Standard execution name makes this idempotent.
            return existing
        self.store.acquire(version_id, now)
        try:
            snapshot = self.extraction.snapshot()
            if not snapshot.items:
                raise ValueError("No approved knowledge to train")
            version = ModelVersion(
                id=version_id,
                manifest={
                    "snapshot_hash": snapshot.sha256,
                    "expected_current_version": self.store.current(),
                    "dev_set_hash": DEV_HASH,
                    "config": self.config.model_dump(mode="json"),
                    "serving_backend": self.config.serving_backend,
                    "created_at": now,
                },
            )
            self.store.save(version)
        except Exception:
            self.store.release(version_id)
            raise
        # Keep lock + pending version on uncertain dispatch; retry the SAME request.
        try:
            self.dispatch(version_id)
        except DispatchRejected:
            version.status = "failed"
            self.store.save(version)
            self.store.release(version_id)
            raise
        return version

    def status(self, version_id: str) -> ModelVersion | None:
        return self.store.get(version_id)

    def versions(self) -> list[ModelVersion]:
        return self.store.versions()
