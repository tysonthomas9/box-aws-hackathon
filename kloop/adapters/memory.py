"""Deterministic fakes; never call external services."""

from copy import deepcopy

from kloop.ports import Record
from kloop.schemas import Document


class MemoryStorage:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], Record] = {}

    def put(self, collection: str, id: str, value: Record) -> None:
        self._records[collection, id] = deepcopy(value)

    def get(self, collection: str, id: str) -> Record | None:
        return deepcopy(self._records.get((collection, id)))

    def list(self, collection: str) -> list[Record]:
        return [
            deepcopy(value)
            for (group, _), value in sorted(self._records.items())
            if group == collection
        ]

    def delete(self, collection: str, id: str) -> None:
        self._records.pop((collection, id), None)


class MemoryArtifacts:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._objects[key] = data

    def get(self, key: str) -> bytes:
        return self._objects[key]

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


class FakeModelClient:
    def __init__(self, text: str = "Canned answer") -> None:
        self.text = text
        self.calls: list[tuple[str, Record]] = []

    def invoke(self, model_id: str, payload: Record) -> Record:
        self.calls.append((model_id, deepcopy(payload)))
        return {"choices": [{"text": self.text}]}


class FakeBoxClient:
    def __init__(self, folders: dict[str, list[Document]] | None = None) -> None:
        self._folders = deepcopy(folders or {})

    def list_documents(self, folder_id: str) -> list[Document]:
        return deepcopy(self._folders.get(folder_id, []))

    def get_document(self, file_id: str, version_id: str) -> Document:
        for documents in self._folders.values():
            for document in documents:
                if (document.file_id, document.version_id) == (file_id, version_id):
                    return document.model_copy(deep=True)
        raise KeyError((file_id, version_id))
