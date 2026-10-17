"""Shared native-token helper spend; a crossed budget stops before more generation."""

import json

from kloop.train.data import encoded, sha256

# Standard rates verified2026-10-17 from AWS Kimi K3 model card and Bedrock pricing.
# Integer nanodollars per token avoid rounding or Dynamo floating-point counters.
RATES = {
    "us.moonshotai.kimi-k3": {
        "inputTokens": 3300,
        "outputTokens": 16500,
        "cacheReadInputTokens": 330,
        "cacheWriteInputTokens": 4125,
    },
    "zai.glm-5": {"inputTokens": 1000, "outputTokens": 3200},
}


class HelperBudgetExceeded(RuntimeError):
    """Generation must stop for coordinator review; this never permits GPU training."""


def generation_id(snapshot_hash, config):
    recipe = {
        key: getattr(config, key)
        for key in (
            "fact_wordings",
            "procedure_cases",
            "unknown_rows",
            "near_miss_rows",
            "replay_rows",
        )
    }
    return sha256(encoded([snapshot_hash, recipe]))


class HelperBudget:
    def __init__(self, table, generation, limit_usd):
        self.table, self.generation = table, generation
        self.limit_nano = round(limit_usd * 1_000_000_000)
        self.key = {"pk": "training_helper_budgets", "sk": generation}

    def total_nano(self):
        return int(
            self.table.get_item(Key=self.key, ConsistentRead=True)
            .get("Item", {})
            .get("spent_nano", 0)
        )

    def check(self):
        if self.total_nano() >= self.limit_nano:
            raise HelperBudgetExceeded(
                "Helper spend reached its limit; coordinator review required"
            )

    def record(self, model, response, request_id):
        usage = response.get("usage")
        if not isinstance(usage, dict) or "inputTokens" not in usage or "outputTokens" not in usage:
            raise ValueError("Native helper usage is required for spend accounting")
        if any(type(usage.get(key, 0)) is not int or usage.get(key, 0) < 0 for key in RATES[model]):
            raise ValueError("Invalid native helper token usage")
        cost = sum(usage.get(key, 0) * rate for key, rate in RATES[model].items())
        if type(cost) is not int or cost < 0:
            raise ValueError("Invalid native helper token usage")
        try:
            self.table.meta.client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": {
                                "pk": f"training_helper_usage:{self.generation}",
                                "sk": request_id,
                                "payload": json.dumps(
                                    {"model": model, "usage": usage, "cost_nano": cost}
                                ),
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": self.key,
                            "UpdateExpression": "ADD spent_nano :cost",
                            "ExpressionAttributeValues": {":cost": cost},
                        }
                    },
                ]
            )
        except self.table.meta.client.exceptions.TransactionCanceledException as exc:
            if (
                exc.response.get("CancellationReasons", [{}])[0].get("Code")
                != "ConditionalCheckFailed"
            ):
                raise
