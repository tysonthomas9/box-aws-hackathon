#!/usr/bin/env python3
"""Register validated, training-ready files (Box shared URLs) in DynamoDB.

Usage:
    python scripts/seed_ddb.py --table <TableName> URL [URL ...]
    python scripts/seed_ddb.py --table <TableName> --file urls.txt

Each row: file_id (derived from the URL), status=validated, validated_at, source_url.
Re-running with the same URL is a no-op for rows already trained.
"""
import argparse
import datetime as dt
import hashlib
import sys
import urllib.parse

import boto3
from botocore.exceptions import ClientError


def file_id_for(url: str) -> str:
    path = urllib.parse.urlparse(url).path.rstrip("/")
    tail = path.rsplit("/", 1)[-1] or "file"
    return f"url-{tail}-{hashlib.sha256(url.encode()).hexdigest()[:8]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--file", help="text file with one URL per line")
    ap.add_argument("urls", nargs="*")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        with open(args.file) as f:
            urls += [u.strip() for u in f if u.strip() and not u.startswith("#")]
    if not urls:
        ap.error("no URLs given")

    table = boto3.resource("dynamodb").Table(args.table)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for url in urls:
        fid = file_id_for(url)
        try:
            table.put_item(
                Item={"file_id": fid, "status": "validated", "validated_at": now, "source_url": url},
                # Don't resurrect rows that were already trained.
                ConditionExpression="attribute_not_exists(file_id) OR #s = :v",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":v": "validated"},
            )
            print(f"validated  {fid}  {url}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            print(f"skipped    {fid}  (already trained)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
