"""Imported-model adapter: normalize only the actionable cold-start exception."""

from typing import Any

from kloop.adapters.aws import BedrockModelClient
from kloop.answer import ModelWarming
from kloop.ports import Record


class ImportedModelClient(BedrockModelClient):
    """Inject a us-east-2 runtime client with SDK retries disabled.

    Answerer owns the configured readiness retry budget. Configure transport timeouts on
    the injected SDK client; smoke.py demonstrates the deployment settings.
    """

    def __init__(self, client: Any) -> None:
        if client.meta.region_name != "us-east-2":
            raise ValueError("Use the selected Region us-east-2")
        super().__init__(client)

    def invoke(self, model_id: str, payload: Record) -> Record:
        try:
            return super().invoke(model_id, payload)
        except self._client.exceptions.ModelNotReadyException as exc:
            raise ModelWarming("Imported model is warming") from exc
