"""API Gateway HTTP API v2 entry point: lambdas.api.handler."""

from functools import lru_cache

from mangum import Mangum

from kloop.web.runtime import api_runtime


@lru_cache(maxsize=1)
def adapter():
    return Mangum(api_runtime(), lifespan="off")


def handler(event, context):
    return adapter()(event, context)
