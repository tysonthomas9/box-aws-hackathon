"""Read-only training controls and observed helper spend for the web app."""

from kloop.train.budget import HelperBudget, generation_id
from kloop.train.config import TrainingConfig


def training_control(store, versions, now):
    lock = store.lock()
    progress = {}
    for version in versions:
        manifest = version.manifest
        spend = None
        if manifest.get("snapshot_hash") and manifest.get("config"):
            config = TrainingConfig.model_validate(manifest["config"])
            generation = generation_id(manifest["snapshot_hash"], config)
            spend = HelperBudget(store.table, generation, config.helper_budget_usd).total_nano()
        progress[version.id] = {
            "helper_spend_usd": spend / 1_000_000_000 if spend is not None else None,
        }
    return {
        "locked": lock is not None,
        "owner": lock.get("owner") if lock else None,
        "expired": bool(lock and int(lock["until"]) <= now),
        "progress": progress,
    }
