"""One version-aware sync path for webhook, scheduled and manual triggers."""

import logging
import time
from collections.abc import Callable
from uuid import uuid4

from kloop.box.client import BoxClient, FileInfo
from kloop.ports import Record, Storage
from kloop.sync.ports import Extraction
from kloop.sync.state import SyncState


def source_files(box: BoxClient) -> list[FileInfo]:
    """Finish every page and subtree before any processing/deletion inference."""
    files = []
    visited = set()

    def visit(folder_id):
        if folder_id in visited:
            raise ValueError("Repeated Box folder in source tree")
        visited.add(folder_id)
        for entry in box.list_folder(folder_id):
            if entry.type == "folder":
                if entry.name.casefold() != "reports":
                    visit(entry.id)
            elif entry.type == "file":
                if entry.name.casefold().endswith((".json", ".jsonl")):
                    logging.getLogger(__name__).warning(
                        "Skipping non-document Box export %s (%s)", entry.id, entry.name
                    )
                    continue
                files.append(box._info(entry))

    visit(box.folder_id)
    return files


class SyncService:
    def __init__(
        self,
        box: BoxClient,
        extraction: Extraction,
        storage: Storage,
        state: SyncState,
        *,
        clock: Callable[[], float] = time.time,
    ):
        self.box, self.extraction, self.storage, self.state = box, extraction, storage, state
        self.clock = clock

    def run(self, trigger: str, event_id: str | None = None) -> Record:
        if trigger not in {"webhook", "schedule", "manual"}:
            raise ValueError("Unknown sync trigger")
        folder = self.box.folder_id
        run_id = uuid4().hex
        started = self.clock()
        row: Record = {
            "id": run_id,
            "folder_id": folder,
            "trigger": trigger,
            "event_id": event_id,
            "started_at": int(started),
            "files_seen": 0,
            "changes": 0,
            "extraction_calls": 0,
            "retirement_calls": 0,
            "status": "running",
            "duration_ms": 0,
        }
        acquired = self.state.acquire(folder, run_id, int(started))
        try:
            if not acquired:
                row["status"] = "busy"
                return row
            self.storage.put("sync_runs", run_id, row)
            # Capture BEFORE listing. Receipts arriving during the scan stay pending.
            pending = self.state.pending(folder)
            files = source_files(self.box)
            row["files_seen"] = len(files)
            collection = f"sync_cursors:{folder}"
            current = {f.file_id for f in files}
            for file in files:
                self._check_deadline(started)
                cursor = self.storage.get(collection, file.file_id)
                if cursor and cursor["version_id"] == file.version_id and not cursor["retired"]:
                    continue
                row["extraction_calls"] += 1
                row["changes"] += self.extraction.process(file.file_id, file.version_id)
                self.storage.put(
                    collection,
                    file.file_id,
                    {
                        "file_id": file.file_id,
                        "version_id": file.version_id,
                        "retired": False,
                    },
                )
            for cursor in self.storage.list(collection):
                self._check_deadline(started)
                if cursor["file_id"] not in current and not cursor["retired"]:
                    row["retirement_calls"] += 1
                    row["changes"] += self.extraction.retire(cursor["file_id"])
                    self.storage.put(collection, cursor["file_id"], {**cursor, "retired": True})
            for receipt in pending:
                self.state.complete(folder, receipt, int(self.clock()))
            row["status"] = "completed"
            return row
        except Exception as exc:
            row["status"] = "failed"
            row["error_type"] = type(exc).__name__  # SDK errors may contain secrets.
            raise
        finally:
            row["duration_ms"] = max(0, int((self.clock() - started) * 1000))
            try:
                self.storage.put("sync_runs", run_id, row)
            finally:
                if acquired:
                    self.state.release(folder, run_id)

    def _check_deadline(self, started: float) -> None:
        if self.clock() - started >= 900:
            raise TimeoutError("Sync exceeded the Lambda execution window")
