"""Restartable workflow actions; resource failures retain ledger ownership."""

import time
from pathlib import Path
from uuid import uuid4

from kloop.answer import ModelWarming
from kloop.schemas import ApprovedSnapshot
from kloop.train.config import MEDICAL_DEV_HASH, TrainingConfig
from kloop.train.data import TrainingRow
from kloop.train.job_request import training_request
from kloop.train.state import INVOCATION_SECONDS, TrainingBusy


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
        base_model_arn=None,
        credit_check=None,
        clock=time.time,
    ):
        self.store, self.snapshots, self.builder = store, snapshots, builder
        self.slots, self.ledger, self.sagemaker = slots, ledger, sagemaker
        self.artifacts, self.serving, self.evaluate = artifacts, serving, evaluate
        self.bucket, self.training_role, self.import_role = bucket, training_role, import_role
        self.dev_bytes = dev_bytes
        self.helpers = helpers
        self.base_model_arn = base_model_arn
        self.credit_check = credit_check
        self.clock = clock

    def handle(
        self, action: str, version_id: str, *, batch: int | None = None, generation_pass: int = 1
    ) -> dict:
        if action in {"cleanup", "release"}:
            return self._handle(action, version_id)
        token, started = uuid4().hex, int(self.clock())
        self.store.begin_invocation(version_id, token, started)
        before_call = getattr(self.helpers, "before_call", None)

        def admit():
            self.store.assert_active(version_id)
            if self.clock() >= started + INVOCATION_SECONDS:
                raise TrainingBusy("Training invocation lifetime ended")

        def helper_admit():
            admit()
            if before_call is not None:
                before_call()

        try:
            if self.helpers is not None:
                self.helpers.before_call = helper_admit
            return self._handle(
                action, version_id, batch=batch, generation_pass=generation_pass, admit=admit
            )
        finally:
            if self.helpers is not None:
                self.helpers.before_call = before_call
            self.store.end_invocation(version_id, token)

    def _handle(
        self, action, version_id, *, batch=None, generation_pass=1, admit=lambda: None
    ) -> dict:
        version = self.store.get(version_id)
        if version is None:
            raise KeyError(version_id)
        self.store.assert_owner(version_id)
        config = TrainingConfig.model_validate(version.manifest["config"])
        if self.credit_check is not None and action in {
            "batches",
            "generate",
            "prepare",
            "import",
            "reimport",
            "warm_current",
            "warm",
            "evaluate",
        }:
            self.credit_check()
        if self.helpers is not None:
            self.helpers.bind_generation(version.manifest["snapshot_hash"], config)
            if action in {"batches", "generate", "prepare"} and self.helpers.budget is not None:
                self.helpers.budget.check()
        import_name = version.manifest.get("active_import_name", version.id)
        if version.manifest["dev_set_hash"] != config.dev_set_hash:
            raise ValueError("Version and recipe dev bindings differ")
        admit()
        if action in {"batches", "generate"}:
            if self.helpers is None:
                raise RuntimeError("Training helper generation is not configured")
            snapshot = ApprovedSnapshot.model_validate(
                self.snapshots.get("approved_snapshots", version.manifest["snapshot_hash"])
            )
            if config.reuse_accepted_items and action == "generate":
                self.helpers.reuse_sources = []
                for raw in version.manifest.get("reuse_sources", []):
                    recipe = TrainingConfig.model_validate(raw)
                    source = ApprovedSnapshot.model_validate(
                        self.snapshots.get("approved_snapshots", recipe.training_snapshot_hash)
                    )
                    if source.sha256 != recipe.training_snapshot_hash:
                        raise ValueError("Reuse source snapshot binding mismatch")
                    self.helpers.reuse_sources.append((source, recipe))
            if action == "batches":
                self.slots.reserve(version.id)
                if self.helpers.budget is not None:
                    version.manifest["helper_generation_id"] = self.helpers.budget.generation
                    version.manifest["helper_budget_usd"] = config.helper_budget_usd
                    self.store.save(version)
                if config.partial_training_key:
                    return {"batches": []}
                return {"batches": list(range(len(self.helpers.batches(snapshot, config))))}
            if type(batch) is not int or not 0 <= batch < len(
                self.helpers.batches(snapshot, config)
            ):
                raise ValueError("Invalid training batch index")
            if type(generation_pass) is not int or not 1 <= generation_pass <= 3:
                raise ValueError("Invalid generation pass")
            self.helpers.generation_pass = generation_pass
            self.helpers.generation_tag = version.id
            rows = list(self.helpers.generate_batch(snapshot, config, batch))
            if not all(
                self.helpers.check(TrainingRow.model_validate(row), snapshot) for row in rows
            ):
                raise ValueError("Semantic checker rejected a training batch")
            target = self.helpers.batches(snapshot, config)[batch][1]
            return {
                "batch": batch,
                "rows": len(rows),
                "complete": len(rows) >= target or generation_pass == 3,
                "generation_pass": generation_pass,
            }
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
            admit()
            version.manifest.update(
                {
                    "manifest_hash": data["manifest_hash"],
                    "data_prefix": data["data_prefix"],
                    "training_rows": data["manifest"]["rows"],
                    "training_row_counts": data["manifest"]["counts"],
                }
            )
            self.store.save(version)
            if (
                config.expected_training_rows is not None
                and abs(data["manifest"]["rows"] - config.expected_training_rows)
                / config.expected_training_rows
                > 0.02
            ):
                raise ValueError(
                    "Training rows differ from the approved recipe by more than2percent"
                )
            if config.expected_training_rows is not None:
                targets = {
                    "fact": sum(i.kind == "fact" for i in snapshot.items) * config.fact_wordings,
                    "procedure": sum(i.kind == "procedure" for i in snapshot.items)
                    * config.procedure_cases,
                    "unknown": config.unknown_rows,
                    "near_miss": config.near_miss_rows,
                    "replay": config.replay_rows,
                }
                if config.partial_training_key:
                    targets = config.partial_training_counts or {}
                    if set(targets) != {"fact", "procedure", "unknown", "replay"} or any(
                        type(count) is not int or count <= 0 for count in targets.values()
                    ):
                        raise ValueError("Partial training requires exact positive count targets")
                if sum(targets.values()) != config.expected_training_rows or any(
                    target and abs(data["manifest"]["counts"].get(kind, 0) - target) / target > 0.02
                    for kind, target in targets.items()
                ):
                    raise ValueError("Training per-kind counts differ from the approved recipe")
            if config.dev_set_hash == MEDICAL_DEV_HASH:
                admit()
                audit = self.evaluate(
                    action="audit",
                    manifest_hash=data["manifest_hash"],
                    snapshot_hash=version.manifest["snapshot_hash"],
                )
                if not audit["passed"]:
                    raise ValueError("Medical rows failed the pre-training overlap audit")
                version.manifest["pretraining_audit"] = audit
            admit()
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
            admit()
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
            result = self.slots.poll(import_name)
            if result["status"] == "Completed":
                version.import_arn = result["importedModelArn"]
                version.manifest["serving_model_id"] = version.import_arn
                version.status = "evaluating"
                self.store.save(version)
            return {"status": result["status"]}
        if action == "warm_current":
            previous = version.manifest["expected_current_version"]
            model = self.store.get(previous).import_arn if previous else self.base_model_arn
            if not model:
                raise ValueError("The dev baseline needs a serving model")
            self.serving.select(config.serving_backend).warm_up(model)
            return {}
        if action == "warm":
            try:
                self.serving.select(config.serving_backend).warm_up(
                    version.manifest["serving_model_id"]
                )
            except ModelWarming:
                if version.manifest.get("reimports", 0):
                    raise RuntimeError(
                        "Model remains unavailable after its one re-import"
                    ) from None
                raise
            return {}
        if action == "reimport":
            retry_name = version.id + "-r1"
            if import_name != retry_name:
                if not self.slots.delete(f"import:{import_name}"):
                    return {"complete": False}
                version.manifest.update(
                    active_import_name=retry_name,
                    reimports=1,
                    import_attempted=False,
                )
                self.store.save(version)
            admit()
            self.slots.reserve(retry_name)
            version.manifest["import_attempted"] = True
            self.store.save(version)
            job = self.slots.create(
                retry_name, self.import_role, f"s3://{self.bucket}/training/{version.id}/merged/"
            )
            version.manifest["import_job_arn"] = job
            version.status = "importing"
            self.store.save(version)
            return {"complete": True, "job_arn": job}
        if action == "evaluate":
            admit()
            result = self.evaluate(
                candidate_arn=version.import_arn,
                snapshot_hash=version.manifest["snapshot_hash"],
                manifest_hash=version.manifest["manifest_hash"],
                expected_current_version=version.manifest["expected_current_version"],
                dev_set_hash=version.manifest["dev_set_hash"],
            )
            version.manifest["evaluation"] = result.model_dump(mode="json")
            version.status = "ready" if result.passed else "rejected"
            if not result.passed and config.dev_set_hash == MEDICAL_DEV_HASH:
                version.manifest["retain_for_medical_report"] = True
            self.store.save(version)
            return {"passed": result.passed}
        if action == "promote":
            admit()
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
            if not version.manifest.get("cleanup_complete") or not self.store.settled(
                version.id, int(self.clock())
            ):
                raise TrainingBusy("Training cleanup has not settled")
            self.store.release(version.id)
            return {}
        raise ValueError("Unknown training action")

    def cleanup(self, version, *, now=None) -> bool:
        now = int(self.clock()) if now is None else now
        fence = self.store.cancel(version.id, now)
        if not self.store.settled(version.id, now):
            return False
        # No admitted invocation can still create resources or overwrite this version.
        version = self.store.get(version.id)
        version.manifest["cancelled_at"] = int(fence["cancelled_at"])
        if not self._cleanup(version):
            self.store.save(version)
            return False
        version.manifest["cleanup_complete"] = True
        self.store.save(version)
        return True

    def _cleanup(self, version) -> bool:
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
        if version.status == "rejected" and version.manifest.get("retain_for_medical_report"):
            return True  # Ledger-owned; coordinator must approve deletion after dev review.
        if not promoted:
            if not self.slots.delete(
                f"import:{version.manifest.get('active_import_name', version.id)}",
                attempted=version.manifest.get("import_attempted", False),
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
        if self.cleanup(version, now=now):
            self.store.release(version_id)  # conditional; never unlock a successor
            return True
        return False
