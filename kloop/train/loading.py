"""Explicit import lifecycle: retain weights, protect readers, never auto-evict."""

from contextlib import contextmanager
from uuid import uuid4

from boto3.dynamodb.conditions import Attr

from kloop.train.service import DispatchRejected
from kloop.train.state import TrainingBusy

LOAD_PREFIX = "kloop-load-"


class ModelGuard:
    """Serialize short Ask/eval admission and unload checks across Lambda instances.

    This lock deliberately has no TTL takeover: a crashed caller needs explicit
    recovery after its Lambda has stopped, rather than admitting a late writer.
    """

    def __init__(self, table):
        self.table = table

    @contextmanager
    def __call__(self):
        owner = str(uuid4())
        key = {"pk": "model_control", "sk": "admission"}
        try:
            self.table.put_item(
                Item={**key, "owner": owner}, ConditionExpression=Attr("pk").not_exists()
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise ValueError("Model operation is busy; try again") from exc
        try:
            yield
        finally:
            self.table.delete_item(Key=key, ConditionExpression=Attr("owner").eq(owner))


class VersionLoading:
    def __init__(
        self,
        store,
        slots,
        dispatch,
        guard,
        weights,
        *,
        clock,
        protected,
        import_role,
        warm,
        temporary=None,
    ):
        self.store, self.slots, self.dispatch = store, slots, dispatch
        self.guard, self.weights, self.clock, self.protected = guard, weights, clock, protected
        self.import_role, self.warm = import_role, warm
        self.temporary = temporary

    def get(self, id):
        value = self.store.get(id)
        if value is None:
            raise KeyError(id)
        return value

    def catalog(self):
        models = self.slots.census()
        protected = self.protected()
        locked = self.store.lock() is not None
        rows = []
        for version in self.store.versions():
            operation = version.manifest.get("loading", {})
            state = operation.get("state")
            if operation.get("action") == "unload":
                state = "loading" if operation["arn"] in models else "not_loaded"
            if state not in {"loading", "failed"}:
                state = "loaded" if version.import_arn in models else "not_loaded"
            rows.append(
                {
                    "id": version.id,
                    "state": state,
                    "import_arn": version.import_arn,
                    "can_load": not locked
                    and state in {"not_loaded", "failed"}
                    and version.status in {"ready", "rejected", "promoted", "failed"}
                    and bool(
                        version.manifest.get("weights") or version.manifest.get("manifest_hash")
                    ),
                    "can_unload": not locked
                    and (state == "loaded" or operation.get("action") == "unload")
                    and (version.import_arn or operation.get("arn")) not in protected,
                    "weights": version.manifest.get("weights"),
                }
            )
        if (
            self.temporary
            and self.temporary["arn"] in models
            and not any(row["import_arn"] == self.temporary["arn"] for row in rows)
        ):
            rows.append(
                {
                    "id": self.temporary["id"],
                    "state": "loaded",
                    "import_arn": self.temporary["arn"],
                    "can_load": False,
                    "can_unload": False,
                    "weights": None,
                }
            )
        return {"versions": rows, "load_active": locked, "slots_used": len(models), "slot_limit": 3}

    def load(self, id):
        existing = self.get(id)
        prior = existing.manifest.get("loading", {})
        lock = self.store.lock() or {}
        if (
            prior.get("state") == "loading"
            and prior.get("action") != "unload"
            and lock.get("owner") == prior.get("owner")
        ):
            self.dispatch(id, prior["owner"])
            return {"id": id, "state": "loading"}
        owner = LOAD_PREFIX + uuid4().hex
        self.store.acquire(owner, int(self.clock()))
        try:
            version = self.get(id)
            if version.import_arn in self.slots.census():
                raise ValueError("Version is already loaded")
            if version.status not in {"ready", "rejected", "promoted", "failed"}:
                raise ValueError("Version has not finished training")
            if len(self.slots.census()) >= 3:
                raise ValueError("All three slots are used; choose a version to unload first")
            if any(
                r["kind"] == "bedrock_import" and not r["resource_id"]
                for r in self.slots.ledger.entries()
            ):
                raise ValueError("A pending import must be reconciled first")
            # Cheap report validation here; full byte verification runs in the worker.
            self.weights(version, False)
            version.manifest["loading"] = {
                "state": "loading",
                "owner": owner,
                "name": owner,
                "attempt": 0,
                "attempted": False,
            }
            self.store.save(version)
        except Exception:
            self.store.release(owner)
            raise
        # Ambiguous dispatch must retain ownership and deterministic execution name.
        try:
            self.dispatch(id, owner)
        except DispatchRejected:
            version.manifest["loading"]["state"] = "failed"
            self.store.save(version)
            self.store.release(owner)
            raise ValueError(
                "Load workflow was refused; try again after configuration is fixed"
            ) from None
        return {
            "id": id,
            "state": "loading",
            "estimate": "Import 10–30 minutes; first answer up to 14 minutes",
        }

    def unload(self, id):
        owner = LOAD_PREFIX + uuid4().hex
        self.store.acquire(owner, int(self.clock()))
        try:
            with self.guard():
                version = self.get(id)
                arn = version.import_arn or version.manifest.get("loading", {}).get("arn")
                if not arn:
                    return {"id": id, "state": "not_loaded"}
                if arn in self.protected() or version.status == "evaluating":
                    raise ValueError("Base, promoted and active models cannot be unloaded")
                row = next(
                    (
                        r
                        for r in self.slots.ledger.entries()
                        if r["resource_id"] == arn and r["kind"] == "bedrock_import"
                    ),
                    None,
                )
                if row is None:
                    raise ValueError("Model is not owned by this deployment")
                # Remove from new Ask selection BEFORE the asynchronous AWS delete.
                version.import_arn = None
                version.manifest.pop("serving_model_id", None)
                version.manifest["loading"] = {"state": "loading", "action": "unload", "arn": arn}
                self.store.save(version)
                if not self.slots.delete(row["key"]):
                    return {"id": id, "state": "loading", "deleting": True}
                version.manifest["loading"] = {"state": "not_loaded"}
                self.store.save(version)
                return {"id": id, "state": "not_loaded"}
        finally:
            self.store.release(owner)

    def step(self, action, id, owner):
        if action in {"fail", "finish"}:
            return self._step(action, id, owner)
        token = uuid4().hex
        self.store.begin_invocation(owner, token, int(self.clock()))
        try:
            return self._step(action, id, owner)
        finally:
            self.store.end_invocation(owner, token)

    def _step(self, action, id, owner):
        self.store.assert_owner(owner)
        if action == "fail":
            self.store.cancel(owner, int(self.clock()))
            if not self.store.settled(owner, int(self.clock())):
                return {"complete": False}
        version = self.get(id)
        operation = version.manifest["loading"]
        if operation["owner"] != owner:
            raise TrainingBusy("Load request was superseded")
        name = operation["name"]
        if action == "create":
            self.weights(version, True)
            # Explicitly refuse eviction; ImportSlots.reserve's training auto-eviction is not used.
            key = f"import:{name}"
            rows = self.slots.ledger.entries()
            if not any(r["key"] == key for r in rows):
                if len(self.slots.census()) >= 3:
                    raise ValueError("Import slots filled; choose an unload first")
                self.slots.ledger.reserve(key, "bedrock_import", name)
            self.store.assert_active(owner)
            operation["attempted"] = True
            self.store.save(version)
            self.slots.create(name, self.import_role, version.manifest["weights"]["s3_uri"])
            return {}
        if action == "poll":
            result = self.slots.poll(name)
            if result["status"] == "Completed":
                operation["arn"] = result["importedModelArn"]
                self.store.save(version)
            return {"status": result["status"]}
        if action == "warm":
            self.warm(operation["arn"])
            version.import_arn = operation["arn"]
            version.manifest["serving_model_id"] = version.import_arn
            operation["state"] = "loaded"
            self.store.save(version)
            return {}
        if action == "reimport":
            if operation["attempt"]:
                raise ValueError("One re-import already attempted")
            if not self.slots.delete(f"import:{name}"):
                return {"complete": False}
            operation.update(name=owner + "-r1", attempt=1, attempted=False)
            self.store.save(version)
            return {"complete": True}
        if action == "finish":
            self.store.release(owner)
            return {}
        if action == "fail":
            operation["state"] = "failed"
            self.store.save(version)
            # Pending AWS creates stay fenced until reconciled. Never drop ownership.
            if not self.slots.delete(f"import:{name}", attempted=operation.get("attempted", False)):
                return {"complete": False}
            self.store.release(owner)
            return {"complete": True}
        raise ValueError("Unknown load action")
