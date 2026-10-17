"""Seed only the frozen POC 2 facts/procedures; no training or held-out questions."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from kloop.box.client import BoxClient, FileInfo
from kloop.ports import Record, Storage

DEFAULT_PACK = Path(__file__).resolve().parents[2] / "poc/company-knowledge/pack.json"


def seed(
    client: BoxClient, pack_path: Path = DEFAULT_PACK, *, storage: Storage | None = None
) -> Record:
    pack_bytes = pack_path.read_bytes()
    pack = json.loads(pack_bytes)
    sources = {}
    for item in [*pack["facts"], *pack["procedures"]]:
        name = item["source"]
        text = item["text"] if "text" in item else item["rule"]
        sources.setdefault(name, []).append(text)
    existing = {item.name: item for item in client.list_folder() if item.type == "file"}
    files: list[Record] = []
    for name, paragraphs in sources.items():
        text = "\n\n".join(paragraphs) + "\n"
        current = existing.get(name)
        if current is None:
            info = client.upload_text(name, text)
        elif client.get_document(current.id, current.file_version.id).text == text:
            info = FileInfo(current.id, current.file_version.id, current.name, current.etag)
        else:
            if not current.etag:
                raise ValueError("Seed requires the inspected file ETag")
            info = client.upload_version(current.id, text, expected_etag=current.etag)
        if client.get_document(info.file_id, info.version_id).text != text:
            raise RuntimeError("Box seed read-after-write verification failed")
        files.append({**asdict(info), "sha256": hashlib.sha256(text.encode()).hexdigest()})
        if storage is not None:
            storage.put("box_sources", name, files[-1])
    manifest: Record = {
        "folder_id": client.folder_id,
        "pack_sha256": hashlib.sha256(pack_bytes).hexdigest(),
        "files": files,
    }
    if storage is not None:
        storage.put("box_seed", "halvard", manifest)
    return manifest
