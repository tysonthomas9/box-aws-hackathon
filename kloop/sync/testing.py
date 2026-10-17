"""Reusable extraction fake; in-memory effects stand in for durable item writes.

This tests orchestration and retry contracts, not real extraction/review policy.
"""


class FakeExtraction:
    def __init__(self):
        self.versions: dict[str, str] = {}
        self.retired: set[str] = set()
        self.calls: list[tuple[str, ...]] = []

    def process(self, file_id: str, version_id: str) -> int:
        self.calls.append(("process", file_id, version_id))
        if self.versions.get(file_id) == version_id and file_id not in self.retired:
            return 0
        self.versions[file_id] = version_id
        self.retired.discard(file_id)
        return 1

    def retire(self, file_id: str) -> int:
        self.calls.append(("retire", file_id))
        if file_id not in self.versions or file_id in self.retired:
            return 0
        self.retired.add(file_id)
        return 1
