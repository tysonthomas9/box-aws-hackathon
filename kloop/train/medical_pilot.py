"""One AWS-side source-only unknown pilot; no training or import path."""

import json

from kloop.schemas import ApprovedSnapshot
from kloop.train.budget import RATES, HelperBudget, generation_id
from kloop.train.config import MEDICAL_DEV_HASH, TrainingConfig
from kloop.train.data import encoded
from kloop.train.helpers import TrainingHelpers

PILOT = "medical-unknown-entities-v1-20261017"
RESULT_KEY = f"training/medical-pilots/{PILOT}.json"
START_KEY = f"training/medical-pilots/{PILOT}-started.json"
LIMIT_NANO = 1_000_000_000


class PilotCostLimit(RuntimeError):
    pass


class PilotRuntime:
    def __init__(self, runtime, budget, baseline):
        self.runtime, self.budget, self.baseline = runtime, budget, baseline

    def converse(self, **request):
        # One invocation owns the training lock, so admission is serial. UTF-8
        # bytes bound text tokens; reserve another 1,024 for message framing.
        text_bytes = sum(
            len(content.get("text", "").encode())
            for message in request["messages"]
            for content in message["content"]
        )
        rates = RATES[request["modelId"]]
        input_rate = max(v for k, v in rates.items() if k != "outputTokens")
        upper_nano = (text_bytes + 1024) * input_rate
        upper_nano += request["inferenceConfig"]["maxTokens"] * rates["outputTokens"]
        if self.budget.total_nano() - self.baseline + upper_nano > LIMIT_NANO:
            raise PilotCostLimit("Pilot stopped before a call could exceed one USD")
        return self.runtime.converse(**request)


class PilotHelpers(TrainingHelpers):
    # Measure the new instruction's initial retention, with no paid repairs.
    # Main training still permits its two source-only repair rounds.
    repair_rounds = 0

    def batches(self, snapshot, config):
        return [("unknown", 5, [item.model_dump(mode="json") for item in snapshot.items])]

    def array_call(self, model, prompt, max_tokens, **kwargs):
        cap = 6000 if model == "us.moonshotai.kimi-k3" else 1024
        return super().array_call(model, prompt, cap, **kwargs)


def run(worker, now):
    artifacts = worker.helpers.artifacts
    try:
        return json.loads(artifacts.get(RESULT_KEY))["summary"]
    except KeyError:
        pass
    config = TrainingConfig()
    if config.dev_set_hash != MEDICAL_DEV_HASH or not config.training_snapshot_hash:
        raise ValueError("Pilot requires the frozen medical source snapshot and dev contract")
    config = config.model_copy(update={"unknown_existing_entities": True})
    worker.credit_check()
    worker.store.acquire(PILOT, now)
    try:
        try:
            return json.loads(artifacts.get(RESULT_KEY))["summary"]
        except KeyError:
            pass
        snapshot = ApprovedSnapshot.model_validate(
            worker.snapshots.get("approved_snapshots", config.training_snapshot_hash)
        )
        if snapshot.sha256 != config.training_snapshot_hash:
            raise ValueError("Pilot snapshot binding mismatch")
        generation = generation_id(snapshot.sha256, config)
        budget = HelperBudget(worker.store.table, generation, config.helper_budget_usd)
        baseline = budget.total_nano()
        try:
            artifacts.get(START_KEY)
        except KeyError:
            artifacts.put(START_KEY, encoded({"baseline_nano": baseline}), "application/json")
        else:
            raise RuntimeError("Pilot already attempted; reconcile before any paid retry")
        helper = PilotHelpers(PilotRuntime(worker.helpers.runtime, budget, baseline), artifacts)
        helper.budget = budget
        error = None
        rows = []
        try:
            rows = list(helper.generate_batch(snapshot, config, 0))
        except PilotCostLimit as exc:
            error = str(exc)
        spent = budget.total_nano() - baseline
        summary = {
            "pilot_id": PILOT,
            "snapshot_hash": snapshot.sha256,
            "requested": 5,
            "repair_rounds": 0,
            "retained": len(rows),
            "passed": len(rows) >= 4,
            "helper_generation_id": generation,
            "baseline_nano": baseline,
            "spent_nano": spent,
            "drop_reports": helper.drop_reports,
            "error": error,
        }
        artifacts.put(RESULT_KEY, encoded({"summary": summary, "rows": rows}), "application/json")
        return summary
    finally:
        worker.store.release(PILOT)
