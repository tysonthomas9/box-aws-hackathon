"""Injected AWS adapters. Constructors do not create clients or resources."""

import json
from typing import Any

from boto3.dynamodb.conditions import Key

from kloop.ports import Record


class DynamoStorage:
    """Table requires string partition key pk (collection) and sort key sk (id).

    JSON is stored as a string so fractional scores retain ordinary JSON numeric
    types across both adapters, without DynamoDB Decimal leaking into core code.
    """

    def __init__(self, table: Any) -> None:
        self._table = table

    def put(self, collection: str, id: str, value: Record) -> None:
        self._table.put_item(
            Item={"pk": collection, "sk": id, "payload": json.dumps(value, allow_nan=False)}
        )

    def get(self, collection: str, id: str) -> Record | None:
        item = self._table.get_item(Key={"pk": collection, "sk": id}, ConsistentRead=True).get(
            "Item"
        )
        return json.loads(item["payload"]) if item else None

    def list(self, collection: str) -> list[Record]:
        paginator = self._table.meta.client.get_paginator("query")
        pages = paginator.paginate(
            TableName=self._table.name,
            KeyConditionExpression=Key("pk").eq(collection),
            ConsistentRead=True,
        )
        return [json.loads(item["payload"]) for page in pages for item in page.get("Items", [])]

    def delete(self, collection: str, id: str) -> None:
        self._table.delete_item(Key={"pk": collection, "sk": id})


class S3Artifacts:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except self._client.exceptions.NoSuchKey as exc:
            raise KeyError(key) from exc
        with response["Body"] as body:
            return body.read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


class BedrockModelClient:
    """Accepts model-native payloads, including the imported Qwen prompt format."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def invoke(self, model_id: str, payload: Record) -> Record:
        response = self._client.invoke_model(
            modelId=model_id,
            body=json.dumps(payload, allow_nan=False),
            contentType="application/json",
            accept="application/json",
        )
        with response["body"] as body:
            result = json.loads(body.read())
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object from InvokeModel")
        return result
