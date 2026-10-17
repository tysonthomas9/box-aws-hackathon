"""Deploy-time Search cache preparation; never invokes a model or changes approval."""

import argparse
import json

import boto3

from kloop.answer.corpus import CorpusStore, fetch_documents, validate_snapshot
from kloop.config import Settings
from kloop.extract.runtime import factory, snapshot_storage


def prepare(aws, sha):
    storage = snapshot_storage(aws)
    snapshot = validate_snapshot(storage.get("approved_snapshots", sha), sha)
    store = CorpusStore(storage.bodies)
    try:
        corpus = store.load(sha)
        return {
            "snapshot_sha256": sha,
            "documents": len(corpus.documents),
            "already_published": True,
        }
    except KeyError:
        pass
    extraction = factory(aws)
    documents = fetch_documents(snapshot, extraction.box.get_document, extraction.retire)
    for document in documents:
        store.save_document(document)
    store.publish(snapshot, documents)
    corpus = store.load(sha)
    return {
        "snapshot_sha256": sha,
        "documents": len(corpus.documents),
        "chunks": len(corpus.index.chunks),
        "already_published": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(boto3.Session(region_name=Settings().region), args.snapshot_sha256)))


if __name__ == "__main__":
    main()
