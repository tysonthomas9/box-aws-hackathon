"""Small application interfaces; adapters take injected service clients."""

from typing import Protocol

from pydantic import JsonValue

from kloop.schemas import Document

Record = dict[str, JsonValue]


class Storage(Protocol):
    """JSON records scoped by collection and id; reads return independent values.

    put replaces an existing record. list is ordered by id. Missing get returns
    None and deleting a missing record succeeds. Locking is a separate concern.
    """

    def put(self, collection: str, id: str, value: Record) -> None: ...
    def get(self, collection: str, id: str) -> Record | None: ...
    def list(self, collection: str) -> list[Record]: ...
    def delete(self, collection: str, id: str) -> None: ...


class Artifacts(Protocol):
    """Bytes by key; missing reads raise KeyError, deletes are idempotent."""

    def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class ModelClient(Protocol):
    """Model-native JSON in/out; prompt rendering and text parsing belong to callers."""

    def invoke(self, model_id: str, payload: Record) -> Record: ...


class BoxClient(Protocol):
    """Read versioned source documents within an explicit folder."""

    def list_documents(self, folder_id: str) -> list[Document]: ...
    def get_document(self, file_id: str, version_id: str) -> Document: ...
