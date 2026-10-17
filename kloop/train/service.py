"""Train now freezes knowledge once, then dispatches a deterministic Standard execution."""

import hashlib

from kloop.schemas import ApprovedSnapshot, ModelVersion
from kloop.train.config import MEDICAL_DEV_HASH, TrainingConfig
from kloop.train.revisions import revision_config


class DispatchRejected(RuntimeError):
    """The service definitively refused to create an execution."""


class TrainingService:
    def __init__(
        self,
        store,
        extraction,
        dispatch,
        config: TrainingConfig,
        *,
        snapshots=None,
        current_approved=False,
    ):
        self.store, self.extraction, self.dispatch, self.config = (
            store,
            extraction,
            dispatch,
            config,
        )
        self.snapshots = snapshots
        self.current_approved = current_approved

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
            config = self.config
            reuse_sources = []
            if self.current_approved:
                snapshot = self.extraction.snapshot()
                reference = snapshot
                if config.training_snapshot_hash:
                    if self.snapshots is None:
                        raise ValueError("Training revisions require immutable snapshot storage")
                    reference = ApprovedSnapshot.model_validate(
                        self.snapshots.get("approved_snapshots", config.training_snapshot_hash)
                    )
                    if reference.sha256 != config.training_snapshot_hash:
                        raise ValueError("Training reference snapshot binding mismatch")
                    reuse_sources.append(config.model_dump(mode="json"))
                reuse_sources.extend(
                    version.manifest["config"]
                    for version in self.store.versions()
                    if version.manifest.get("config", {}).get("training_snapshot_hash")
                )
                config = revision_config(snapshot, reference, config)
            elif self.config.training_snapshot_hash:
                if self.snapshots is None:
                    raise ValueError("Pinned training requires immutable snapshot storage")
                snapshot = ApprovedSnapshot.model_validate(
                    self.snapshots.get("approved_snapshots", self.config.training_snapshot_hash)
                )
                if snapshot.sha256 != self.config.training_snapshot_hash:
                    raise ValueError("Training snapshot binding mismatch")
            elif self.config.dev_set_hash == MEDICAL_DEV_HASH:
                raise ValueError("Medical training requires the selected training snapshot")
            else:
                snapshot = self.extraction.snapshot()
            if not snapshot.items:
                raise ValueError("No approved knowledge to train")
            version = ModelVersion(
                id=version_id,
                manifest={
                    "snapshot_hash": snapshot.sha256,
                    "expected_current_version": self.store.current(),
                    "dev_set_hash": self.config.dev_set_hash,
                    "config": config.model_dump(mode="json"),
                    "reuse_sources": reuse_sources,
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
