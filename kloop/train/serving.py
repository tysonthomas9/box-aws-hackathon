"""Serving seam: transaction and promotion do not depend on inference transport."""

from typing import Protocol


class ServingBackend(Protocol):
    def warm_up(self, model_id: str) -> object: ...
    def answer_with(self, question: str, model_id: str) -> object: ...


class ServingBackends:
    def __init__(self, backends: dict[str, ServingBackend]):
        self.backends = backends

    def select(self, name: str) -> ServingBackend:
        try:
            return self.backends[name]
        except KeyError as exc:
            raise ValueError(f"Serving backend is not configured: {name}") from exc
