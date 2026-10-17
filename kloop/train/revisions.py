"""Freeze a current approval revision without changing earlier training manifests."""

from kloop.train.config import TrainingConfig


def knowledge_rows(snapshot, config):
    return sum(
        config.fact_wordings if item.kind == "fact" else config.procedure_cases
        for item in snapshot.items
    )


def revision_config(snapshot, reference, config):
    """Keep wordings per item; scale controls by knowledge rows, rounded half up.

    The reference recipe is immutable (medical v1: 1576 knowledge rows,
    400 unknown, 220 near-miss, 490 replay). Each control retains at least one
    row. Validate rather than cap large revisions: no silent recipe dilution.
    """
    knowledge = knowledge_rows(snapshot, config)
    baseline = knowledge_rows(reference, config)
    if not knowledge or not baseline:
        raise ValueError("Training revision requires approved knowledge")
    controls = {
        kind: max(1, (getattr(config, kind) * knowledge * 2 + baseline) // (2 * baseline))
        for kind in ("unknown_rows", "near_miss_rows", "replay_rows")
    }
    return TrainingConfig.model_validate(
        {
            **config.model_dump(mode="json"),
            **controls,
            "training_snapshot_hash": snapshot.sha256,
            "expected_training_rows": knowledge + sum(controls.values()),
            "preserve_accepted_batches": True,
            "reuse_accepted_items": True,
            "partial_training_key": None,
            "partial_training_counts": None,
        }
    )
