"""Join recorded sync activity to webhook receipts and current review counts."""

from collections import Counter

from boto3.dynamodb.conditions import Key


def source_activity(files, runs, receipts_table, folder_id, reviews):
    pages = receipts_table.meta.client.get_paginator("query").paginate(
        TableName=receipts_table.name,
        KeyConditionExpression=Key("pk").eq(f"receipts:{folder_id}"),
        ConsistentRead=True,
    )
    receipts = {
        row["sk"]: {
            "event_id": row["sk"],
            "received_at": int(row["received_at"]),
            "event_type": row.get("event_type"),
            "pending": "expires_at" not in row,
        }
        for page in pages
        for row in page.get("Items", [])
    }
    waiting = Counter(r.source_file_id for r in reviews)
    names = {
        file["file_id"]: file["name"]
        for run in reversed(runs)
        for file in run.get("changed_files", [])
        if file.get("name") and file["name"] != file["file_id"]
    }
    names.update(
        {
            file["file_id"]: file["name"]
            for file in files
            if file.get("name") and file["name"] != file["file_id"]
        }
    )
    activity = []
    for run in runs:
        value = {**run, "webhook": receipts.get(run.get("event_id"))}
        if "changed_files" in run:
            value["changed_files"] = [
                {
                    **file,
                    "name": file.get("name")
                    if file.get("name") != file["file_id"]
                    else names.get(file["file_id"], file.get("name")),
                    "waiting_review": waiting[file["file_id"]],
                }
                for file in run["changed_files"]
            ]
        activity.append(value)
    return {
        "files": [
            {
                **file,
                "name": names.get(file["file_id"], file.get("name")),
                "waiting_review": waiting[file["file_id"]],
            }
            for file in files
        ],
        "runs": activity,
        "events": sorted(receipts.values(), key=lambda r: r["received_at"], reverse=True)[:20],
    }
