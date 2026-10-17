"""PrepareDataset Lambda (Option A).

1. Query DynamoDB for files with status=validated.
2. Guard: stop early if fewer than MIN_NEW_EXAMPLES.
3. For each file, fetch extracted text + validated label from Box.
4. Build an accumulating dataset: previous snapshot + new examples -> new S3 snapshot.
5. Mark processed rows status=trained in DynamoDB.
6. Return S3 URIs + a unique SageMaker job name for the next state.
"""
import datetime as dt
import json
import logging
import os
import uuid

import boto3
from boto3.dynamodb.conditions import Key

from box_client import BoxClient, BoxError
from url_source import UrlFetchError, fetch_example

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
STATUS_INDEX = os.environ["STATUS_INDEX"]
BUCKET_NAME = os.environ["BUCKET_NAME"]
BOX_SECRET_NAME = os.environ["BOX_SECRET_NAME"]
BOX_METADATA_TEMPLATE = os.environ["BOX_METADATA_TEMPLATE"]
MIN_NEW_EXAMPLES = int(os.environ.get("MIN_NEW_EXAMPLES", "50"))

LATEST_POINTER_KEY = "datasets/latest.json"
PROMPT_PREFIX = "Extract the structured fields from this document as JSON:\n\n"

_ddb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")
_table = _ddb.Table(TABLE_NAME)


def _query_validated() -> list[dict]:
    items, kwargs = [], {
        "IndexName": STATUS_INDEX,
        "KeyConditionExpression": Key("status").eq("validated"),
    }
    while True:
        resp = _table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _load_previous_snapshot() -> str:
    """Return the previous accumulated train.jsonl content, or '' on first run."""
    try:
        pointer = json.loads(_s3.get_object(Bucket=BUCKET_NAME, Key=LATEST_POINTER_KEY)["Body"].read())
    except _s3.exceptions.NoSuchKey:
        return ""
    body = _s3.get_object(Bucket=BUCKET_NAME, Key=pointer["train_key"])["Body"].read().decode("utf-8")
    return body if body.endswith("\n") or not body else body + "\n"


def _to_example(raw_text: str, label: dict) -> str:
    return json.dumps(
        {
            "messages": [
                {"role": "user", "content": PROMPT_PREFIX + raw_text},
                {"role": "assistant", "content": json.dumps(label, ensure_ascii=False, sort_keys=True)},
            ]
        },
        ensure_ascii=False,
    )


def _mark_trained(file_ids: list[str], run_tag: str) -> None:
    for fid in file_ids:
        # update_item keeps validated_at intact (it is the GSI sort key).
        _table.update_item(
            Key={"file_id": fid},
            UpdateExpression="SET #s = :trained, trained_in = :tag",
            ConditionExpression="#s = :validated",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":trained": "trained", ":validated": "validated", ":tag": run_tag},
        )


def lambda_handler(event, _context):
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")

    # Pre-built dataset mode: the execution input names an S3 prefix that already holds
    # train.jsonl (e.g. a bulk corpus labelled offline). Skip DynamoDB/Box and go straight to training.
    prebuilt = (event or {}).get("prebuilt_train_s3_uri")
    if prebuilt:
        if not prebuilt.startswith(f"s3://{BUCKET_NAME}/datasets/"):
            raise ValueError("prebuilt_train_s3_uri must be under this pipeline's datasets/ prefix")
        return _run_outputs(run_id, prebuilt.rstrip("/") + "/", new=None, total=None, failed=[])

    validated = _query_validated()
    logger.info("Found %d validated files", len(validated))

    if len(validated) < MIN_NEW_EXAMPLES:
        return {
            "enough_data": False,
            "new_example_count": len(validated),
            "reason": f"{len(validated)} new validated files < MIN_NEW_EXAMPLES={MIN_NEW_EXAMPLES}",
        }

    box = None  # created lazily; URL-sourced rows don't need Box API credentials

    new_lines, ok_ids, failed = [], [], []
    for item in validated:
        fid = item["file_id"]
        try:
            if item.get("source_url"):
                # Training-ready JSON ({"input", "output"}) at a Box shared URL.
                text, label = fetch_example(item["source_url"])
            else:
                # Raw Box file + label in a Box metadata template.
                box = box or BoxClient.from_secret(BOX_SECRET_NAME)
                text = box.get_text(fid)
                label = box.get_validated_label(fid, BOX_METADATA_TEMPLATE)
            if not text.strip() or not label:
                raise BoxError("empty text or label")
            new_lines.append(_to_example(text, label))
            ok_ids.append(fid)
        except (BoxError, UrlFetchError) as e:
            # Leave the row as 'validated' so it is retried on the next run.
            logger.warning("Skipping file %s: %s", fid, e)
            failed.append(fid)

    if len(new_lines) < MIN_NEW_EXAMPLES:
        return {
            "enough_data": False,
            "new_example_count": len(new_lines),
            "failed_files": failed,
            "reason": f"Only {len(new_lines)} files fetched successfully from Box",
        }

    # Accumulate: previous snapshot + new examples, written as a new immutable snapshot.
    previous = _load_previous_snapshot()
    train_key = f"datasets/{run_id}/train.jsonl"
    body = previous + "\n".join(new_lines) + "\n"
    _s3.put_object(Bucket=BUCKET_NAME, Key=train_key, Body=body.encode("utf-8"))

    total = body.count("\n")
    _s3.put_object(
        Bucket=BUCKET_NAME,
        Key=LATEST_POINTER_KEY,
        Body=json.dumps({"run_id": run_id, "train_key": train_key, "total_examples": total}).encode(),
    )

    _mark_trained(ok_ids, f"run-{run_id}")
    logger.info("Wrote %s (%d total, %d new)", train_key, total, len(new_lines))

    return _run_outputs(run_id, f"s3://{BUCKET_NAME}/datasets/{run_id}/", new=len(new_lines), total=total, failed=failed)


def _run_outputs(run_id: str, train_s3_uri: str, new, total, failed) -> dict:
    return {
        "enough_data": True,
        "run_id": run_id,
        "new_example_count": new,
        "total_example_count": total,
        "failed_files": failed,
        "train_s3_uri": train_s3_uri,
        "output_s3_uri": f"s3://{BUCKET_NAME}/models/{run_id}/",
        # Raw merged HF weights for Bedrock Custom Model Import.
        "export_s3_uri": f"s3://{BUCKET_NAME}/models/{run_id}/hf/",
        "imported_model_name": f"pharma-qwen-{run_id}",
        "import_job_name": f"pharma-qwen-import-{run_id}-{uuid.uuid4().hex[:6]}",
        # SageMaker job names: <=63 chars, alphanumeric + hyphens.
        "job_name": f"qwen-qlora-{run_id}-{uuid.uuid4().hex[:6]}",
    }
