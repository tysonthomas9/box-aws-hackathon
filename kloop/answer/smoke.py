"""Live inference smoke; uses retained imports and creates no cloud resources.

Run make answer-smoke with KLOOP_BASE_MODEL_ID and
KLOOP_SMOKE_TRAINED_MODEL_ARN set to explicit imported-model ARNs.
AWS_PROFILE defaults to box-hackathon; deployment clients use the role chain.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.config import Config

from kloop.answer import Answerer
from kloop.answer.bedrock import ImportedModelClient
from kloop.config import Settings
from kloop.schemas import Document


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model-arn", default=settings.base_model_id)
    parser.add_argument("--trained-model-arn", default=os.getenv("KLOOP_SMOKE_TRAINED_MODEL_ARN"))
    args = parser.parse_args()
    if not args.base_model_arn or not args.trained_model_arn:
        parser.error("Set KLOOP_BASE_MODEL_ID and KLOOP_SMOKE_TRAINED_MODEL_ARN")
    pack = json.loads(Path("poc/company-knowledge/pack.json").read_text())
    # Local fixture mirrors the frozen, approved POC pack; not a Box integration test.
    fact = pack["facts"][0]
    documents = [
        Document(
            file_id=fact["id"], version_id="poc2-frozen", name=fact["source"], text=fact["text"]
        )
    ]
    session = boto3.Session(
        profile_name=os.getenv("AWS_PROFILE", "box-hackathon"), region_name=settings.region
    )
    runtime = session.client(
        "bedrock-runtime",
        config=Config(
            retries={"total_max_attempts": 1, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
        ),
    )
    answerer = Answerer(
        ImportedModelClient(runtime),
        on_status=lambda status: print(json.dumps({"status": status}), flush=True),
    )
    question = "Who owns the Kestrel service?"
    for mode, run in (
        ("without", lambda: answerer.answer_without(question, args.base_model_arn)),
        ("with", lambda: answerer.answer_with(question, args.trained_model_arn)),
        ("search", lambda: answerer.answer_search(question, args.base_model_arn, documents)),
    ):
        result = run()
        if mode == "search" and not result.citations:
            raise ValueError("Search smoke must return a real citation")
        print(
            json.dumps(
                {"mode": mode, "completed_at": datetime.now(UTC).isoformat(), **result.model_dump()}
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
