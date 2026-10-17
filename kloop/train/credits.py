"""Fail closed before paid actions if AWS credits cannot be confirmed above the floor."""

import math


class AWSCreditFloor(RuntimeError):
    pass


class CreditGuard:
    def __init__(self, client, minimum_usd):
        self.client, self.minimum_usd = client, minimum_usd

    def check(self):
        try:
            value = self.client.get_account_plan_state()["accountPlanRemainingCredits"]
            amount = value["amount"]
            if (
                value["unit"] != "USD"
                or type(amount) not in (int, float)
                or not math.isfinite(amount)
                or amount < self.minimum_usd
            ):
                raise ValueError("AWS credit balance is below the floor or invalid")
        except Exception as exc:
            raise AWSCreditFloor(
                "Paid work stopped: AWS USD credits must be confirmed at the floor"
            ) from exc
        return amount


class CreditCheckedRuntime:
    def __init__(self, runtime, guard):
        self.runtime, self.guard = runtime, guard
        self.meta, self.exceptions = runtime.meta, runtime.exceptions

    def converse(self, **request):
        self.guard.check()
        return self.runtime.converse(**request)

    def invoke_model(self, **request):
        self.guard.check()
        return self.runtime.invoke_model(**request)
