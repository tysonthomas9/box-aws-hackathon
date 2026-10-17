"""Snapshot-bound Search corpora, published by extraction; Ask only reads them."""

import json
import logging
import time
from functools import lru_cache

from box_sdk_gen.box.errors import BoxAPIError

from kloop.answer import SearchIndex
from kloop.extract.hashing import digest
from kloop.extract.repository import ConcurrentUpdate
from kloop.extract.snapshots import snapshot_key
from kloop.schemas import ApprovedSnapshot, Document, Schema

logger = logging.getLogger(__name__)


def corpus_key(sha):
    return snapshot_key(sha).removesuffix(".json") + ".search.json"


def document_key(file, version):
    return f"extraction/snapshots/documents/{digest([file, version])}.json"


def quotes_for(snapshot, documents):
    quotes = {(d.file_id, d.version_id): [] for d in documents}
    for item in snapshot.items:
        pair = (item.source_file_id, item.source_version_id)
        if pair in quotes:
            quotes[pair].append(item.supporting_quote)
    return quotes


def validate_snapshot(value, sha):
    if value is None:
        raise ValueError("Pinned snapshot is missing")
    snapshot = ApprovedSnapshot.model_validate(value)
    if snapshot.sha256 != sha or digest([i.model_dump(mode="json") for i in snapshot.items]) != sha:
        raise ValueError("Pinned snapshot failed integrity check")
    return snapshot


def fetch_documents(snapshot, get_document, retire):
    """Keep unavailable-source skips and retirement review identical to the live path."""
    documents = []
    started = time.monotonic()
    for file, version in sorted({(i.source_file_id, i.source_version_id) for i in snapshot.items}):
        try:
            document = get_document(file, version)
        except (BoxAPIError, PermissionError) as error:
            if isinstance(error, BoxAPIError) and error.response_info.status_code not in {
                403,
                404,
                410,
            }:
                raise
            logger.warning(
                "Search skipped unavailable source %s version %s; retirement review requested",
                file,
                version,
            )
            try:
                retire(file)
            except ConcurrentUpdate:
                logger.warning("Retirement review deferred by concurrent update for %s", file)
            continue
        if (document.file_id, document.version_id) != (file, version):
            raise ValueError("Source version differs from pinned snapshot")
        documents.append(document)
    logger.info(
        "Search source_fetch_ms=%.2f documents=%d",
        (time.monotonic() - started) * 1000,
        len(documents),
    )
    return documents


class SearchCorpus(Schema):
    snapshot_sha256: str
    documents: list[Document]
    index: SearchIndex

    @classmethod
    def build(cls, snapshot, documents):
        return cls(
            snapshot_sha256=snapshot.sha256,
            documents=documents,
            index=SearchIndex.build(documents, approved_quotes=quotes_for(snapshot, documents)),
        )


class CorpusStore:
    def __init__(self, bodies):
        self.bodies = bodies
        self.load = lru_cache(maxsize=2)(self._load)

    def save_document(self, document):
        self.bodies.put(
            document_key(document.file_id, document.version_id), document.model_dump_json().encode()
        )

    def _load(self, sha):
        started = time.monotonic()
        value = json.loads(self.bodies.get(corpus_key(sha)))
        payload = value["corpus"]
        if digest(payload) != value["sha256"]:
            raise ValueError("Search corpus failed integrity check")
        corpus = SearchCorpus.model_validate(payload)
        if corpus.snapshot_sha256 != sha:
            raise ValueError("Search corpus snapshot differs")
        logger.info(
            "Search corpus_load_ms=%.2f snapshot=%s", (time.monotonic() - started) * 1000, sha
        )
        return corpus

    def publish(self, snapshot, documents=None):
        """No Box fetches in API snapshot reads; missing documents keep the live fallback."""
        try:
            self.load(snapshot.sha256)
            return True
        except KeyError:
            pass
        if documents is None:
            documents = []
            for file, version in sorted(
                {(i.source_file_id, i.source_version_id) for i in snapshot.items}
            ):
                try:
                    document = Document.model_validate_json(
                        self.bodies.get(document_key(file, version))
                    )
                except KeyError:
                    return False
                if (document.file_id, document.version_id) != (file, version):
                    raise ValueError("Cached source version differs from pinned snapshot")
                documents.append(document)
        corpus = SearchCorpus.build(snapshot, documents)
        payload = corpus.model_dump(mode="json")
        body = json.dumps({"corpus": payload, "sha256": digest(payload)}, sort_keys=True).encode()
        self.bodies.put(corpus_key(snapshot.sha256), body)
        self.load(snapshot.sha256)
        return True
