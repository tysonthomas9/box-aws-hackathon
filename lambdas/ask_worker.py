"""SQS partial-batch entry point: lambdas.ask_worker.handler."""

import logging

from kloop.web.runtime import worker_runtime

logging.getLogger("kloop.web.jobs").setLevel(logging.INFO)
logging.getLogger("kloop.web.runtime").setLevel(logging.INFO)
logging.getLogger("kloop.answer.corpus").setLevel(logging.INFO)


def handler(event, context):
    return worker_runtime().handle(event)
