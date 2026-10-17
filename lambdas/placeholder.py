"""Wave-2 wiring only. Every application route fails closed until integration."""

import hmac
import json
import os
from functools import cache
from time import perf_counter

import boto3

_import_start = perf_counter()
import box_sdk_gen  # noqa: E402,F401
import fastapi  # noqa: E402,F401
import mangum  # noqa: E402,F401

IMPORT_SECONDS = perf_counter() - _import_start


@cache
def origin_secret():
    client = boto3.client("secretsmanager", region_name="us-east-2")
    return client.get_secret_value(SecretId=os.environ["KLOOP_ORIGIN_SECRET_ID"])["SecretString"]


def handler(event, context):
    if os.environ["KLOOP_ROLE"] != "api":
        raise RuntimeError("Placeholder: application integration has not been deployed")
    supplied = event.get("headers", {}).get("x-kloop-origin", "")
    if (
        not supplied
        or supplied == "unconfigured"
        or not hmac.compare_digest(supplied, origin_secret())
    ):
        return {"statusCode": 403, "body": "Forbidden"}
    # Health is a temporary wiring proof; all product routes stay unavailable.
    if event.get("rawPath") == "/api/health":
        return {
            "statusCode": 200,
            "headers": {"content-type": "application/json"},
            "body": json.dumps(
                {
                    "status": "placeholder",
                    "integrated": False,
                    "cold_import_seconds": IMPORT_SECONDS,
                }
            ),
        }
    return {"statusCode": 503, "body": "Application integration pending"}
