"""SQS partial-batch entry point: lambdas.ask_worker.handler."""

from kloop.web.runtime import worker_runtime


def handler(event, context):
    return worker_runtime().handle(event)
