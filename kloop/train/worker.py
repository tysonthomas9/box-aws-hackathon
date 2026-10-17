"""Restartable workflow actions; resource failures retain ledger ownership."""

from pathlib import Path

from kloop.schemas import ApprovedSnapshot
from kloop.train.config import MEDICAL_DEV_HASH, TrainingConfig
from kloop.train.data import TrainingRow
from kloop.train.job_request import training_request


class TrainingWorker:
    def __init__(
        self,
        store,
        snapshots,
        builder,
        slots,
        ledger,
        sagemaker,
        artifacts,
        serving,
        evaluate,
        *,
        bucket,
        training_role,
        import_role,
        dev_bytes,
        helpers=None,
    ):
        self.store, self.snapshots, self.builder = store, snapshots, builder
        self.slots, self.ledger, self.sagemaker = slots, ledger, sagemaker
        self.artifacts, self.serving, self.evaluate = artifacts, serving, evaluate
        self.bucket, self.training_role, self.import_role = bucket, training_role, import_role
        self.dev_bytes = dev_bytes
        self.helpers = helpers

    def handle(self, action: str, version_id: str, *, batch: int | None = None) -> dict:
        version = self.store.get(version_id)
        if version is None:
            raise KeyError(version_id)
        self.store.assert_owner(version_id)
        config = TrainingConfig.model_validate(version.manifest["config"])
        if version.manifest["dev_set_hash"] != config.dev_set_hash:
            raise ValueError("Version and recipe dev bindings differ")
        if action in {"batches", "generate"}:
            if self.helpers is None:
                raise RuntimeError("Training helper generation is not configured")
            snapshot = ApprovedSnapshot.model_validate(
                self.snapshots.get("approved_snapshots", version.manifest["snapshot_hash"])
            )
            if action == "batches":
                self.slots.reserve(version.id)
                return {"batches": list(range(len(self.helpers.batches(snapshot, config))))}
            if type(batch) is not int or not 0 <= batch < len(
                self.helpers.batches(snapshot, config)
            ):
                raise ValueError("Invalid training batch index")
            rows = list(self.helpers.generate_batch(snapshot, config, batch))
            if not all(
                self.helpers.check(TrainingRow.model_validate(row), snapshot) for row in rows
            ):
                raise ValueError("Semantic checker rejected a training batch")
            return {"batch": batch, "rows": len(rows)}
        if action == "prepare":
            # Census and reservation happen before data generation or GPU spend.
            if any(
                r["kind"] == "sagemaker_training" and r["key"] != f"training:{version.id}"
                for r in self.ledger.entries()
            ):
                raise RuntimeError("Prior training resource needs reconciliation")
            self.slots.reserve(version.id)
            snapshot = ApprovedSnapshot.model_validate(
                self.snapshots.get("approved_snapshots", version.manifest["snapshot_hash"])
            )
            data = self.builder.build(snapshot, config, self.dev_bytes)
            version.manifest.update(
                {"manifest_hash": data["manifest_hash"], "data_prefix": data["data_prefix"]}
            )
            self.store.save(version)
            if config.dev_set_hash == MEDICAL_DEV_HASH:
                audit = self.evaluate(
                    action="audit",
                    manifest_hash=data["manifest_hash"],
                    snapshot_hash=version.manifest["snapshot_hash"],
                )
                if not audit["passed"]:
                    raise ValueError("Medical rows failed the pre-training overlap audit")
                version.manifest["pretraining_audit"] = audit
            self.artifacts.put(
                f"training/{version.id}/code/job.py",
                Path(__file__).with_name("job.py").read_bytes(),
                "text/x-python",
            )
            key = f"training:{version.id}"
            if not any(r["key"] == key for r in self.ledger.entries()):
                self.ledger.reserve(key, "sagemaker_training", version.id)
            version.status = "training"
            self.store.save(version)
            return {
                "request": training_request(
                    config, version.id, self.bucket, self.training_role, data["data_prefix"]
                )
            }
        if action == "import":
            details = self.sagemaker.describe_training_job(TrainingJobName=version.id)
            if details["TrainingJobStatus"] != "Completed":
                raise RuntimeError("Training did not complete")
            self.ledger.resolve(f"training:{version.id}", details["TrainingJobArn"])
            if len(self.slots.census()) >= 3:
                raise RuntimeError("Import slots filled during training; refuse create")
            version.manifest["import_attempted"] = True
            self.store.save(version)
            job = self.slots.create(
                version.id, self.import_role, f"s3://{self.bucket}/training/{version.id}/merged/"
            )
            version.status = "importing"
            version.manifest["import_job_arn"] = job
            self.store.save(version)
            return {"job_arn": job}
        if action == "poll":
            result = self.slots.poll(version.id)
            if result["status"] == "Completed":
                version.import_arn = result["importedModelArn"]
                version.manifest["serving_model_id"] = version.import_arn
                version.status = "evaluating"
                self.store.save(version)
            return {"status": result["status"]}
        if action == "warm":
            self.serving.select(config.serving_backend).warm_up(
                version.manifest["serving_model_id"]
            )
            return {}
        if action == "evaluate":
            result = self.evaluate(
                candidate_arn=version.import_arn,
                snapshot_hash=version.manifest["snapshot_hash"],
                manifest_hash=version.manifest["manifest_hash"],
                expected_current_version=version.manifest["expected_current_version"],
                dev_set_hash=version.manifest["dev_set_hash"],
            )
            version.manifest["evaluation"] = result.model_dump(mode="json")
            version.status = "ready" if result.passed else "rejected"
            self.store.save(version)
            return {"passed": result.passed}
        if action == "promote":
            if version.status == "promoted" and self.store.current() == version.id:
                return {"promoted": True}
            if version.status != "ready" or not version.manifest["evaluation"]["passed"]:
                raise RuntimeError("Cannot promote without a passing dev gate")
            passed = self.store.promote(version, version.manifest["expected_current_version"])
            if not passed:
                version.status = "rejected"
                version.manifest["promotion_error"] = "Current version changed during training"
                self.store.save(version)
            return {"promoted": passed}
        if action == "cleanup":
            return {"complete": self.cleanup(version)}
        if action == "release":
            self.store.release(version.id)
            return {}
        raise ValueError("Unknown training action")

    def cleanup(self, version) -> bool:
        # Stop/settle GPU before releasing the lock. Failed attempts are retryable.
        row = next((r for r in self.ledger.entries() if r["key"] == f"training:{version.id}"), None)
        if row:
            try:
                job = self.sagemaker.describe_training_job(TrainingJobName=version.id)
                if job["TrainingJobStatus"] in {"InProgress", "Stopping"}:
                    if job["TrainingJobStatus"] == "InProgress":
                        self.sagemaker.stop_training_job(TrainingJobName=version.id)
                    return False
                self.ledger.resolve(row["key"], job["TrainingJobArn"])
                row = next(r for r in self.ledger.entries() if r["key"] == row["key"])
                self.ledger.remove(row)
            except self.sagemaker.exceptions.ResourceNotFound:
                # Cleanup runs after the .sync state exits. Reconcile its exact
                # deterministic job name; absence means no GPU resource to stop.
                self.ledger.remove(row)
        promoted = self.store.current() == version.id
        if not promoted:
            if not self.slots.delete(
                f"import:{version.id}", attempted=version.manifest.get("import_attempted", False)
            ):
                return False
            if version.status not in {"rejected", "failed"}:
                version.status = "failed"
                self.store.save(version)
        return True

    def recover(self, version_id: str, execution_status: str, now: int) -> bool:
        lock = self.store.lock()
        if execution_status not in {"FAILED", "TIMED_OUT", "ABORTED", "SUCCEEDED"}:
            raise RuntimeError("Refuse lock recovery while its execution may still run")
        if lock and lock["owner"] == version_id:
            if now < lock["until"] and execution_status == "SUCCEEDED":
                raise RuntimeError("Successful execution has not reached lease recovery time")
        version = self.store.get(version_id)
        if version is None:
            raise KeyError(version_id)
        if self.cleanup(version):
            self.store.release(version_id)  # conditional; never unlock a successor
            return True
        return False
