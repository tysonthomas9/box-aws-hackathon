"""Pinned per-mode jobs, CAS ownership, bounded cold starts, and SQS redelivery."""

import json
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4

from boto3.dynamodb.conditions import Attr

from kloop.answer import Answerer, ModelWarming
from kloop.schemas import AskJob, Document, PinnedModel

TERMINAL = {"succeeded", "failed"}
BUDGET = 900


@dataclass(frozen=True)
class SearchEvidence:
    documents: list[Document]
    approved_quotes: dict[tuple[str, str], list[str]]


class MemoryJobs:
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()
        self.warm_lease = None

    def acquire_warm(self, id, now, until):
        with self.lock:
            if self.warm_lease and self.warm_lease[1] > now:
                return False
            self.warm_lease = (id, until)
            return True

    def release_warm(self, id):
        with self.lock:
            if self.warm_lease and self.warm_lease[0] == id:
                self.warm_lease = None

    def read(self, id):
        with self.lock:
            row = self.rows.get(id)
            return deepcopy(row) if row else (None, 0)

    def save(self, job, revision):
        with self.lock:
            if self.rows.get(job.id, (None, 0))[1] != revision:
                return False
            self.rows[job.id] = (job.model_copy(deep=True), revision + 1)
            return True


class DynamoJobs:
    def __init__(self, table):
        self.table = table

    def acquire_warm(self, id, now, until):
        try:
            self.table.put_item(
                Item={"pk": "web_locks", "sk": "warm_up", "owner": id, "until": until},
                ConditionExpression=Attr("pk").not_exists() | Attr("until").lte(now),
            )
            return True
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def release_warm(self, id):
        try:
            self.table.delete_item(
                Key={"pk": "web_locks", "sk": "warm_up"},
                ConditionExpression=Attr("owner").eq(id),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            pass

    def read(self, id):
        row = self.table.get_item(Key={"pk": "ask_jobs", "sk": id}, ConsistentRead=True).get("Item")
        return (
            (AskJob.model_validate_json(row["payload"]), int(row["revision"])) if row else (None, 0)
        )

    def save(self, job, revision):
        try:
            self.table.put_item(
                Item={
                    "pk": "ask_jobs",
                    "sk": job.id,
                    "payload": job.model_dump_json(),
                    "revision": revision + 1,
                    "expires_at": job.expires_at + 86400,
                },
                ConditionExpression=Attr("revision").eq(revision)
                if revision
                else Attr("pk").not_exists(),
            )
            return True
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False


class SQSDispatch:
    def __init__(self, client, queue_url):
        self.client, self.queue_url = client, queue_url

    def __call__(self, id):
        self.client.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps({"job_id": id}))


class JobService:
    def __init__(self, store, dispatch, *, clock=time.time):
        self.store, self.dispatch, self.clock = store, dispatch, clock

    def create(
        self,
        question,
        mode,
        model_arn,
        version_id,
        snapshot_sha256,
        *,
        warm_up=False,
        warm_up_models=(),
    ):
        now = int(self.clock())
        job = AskJob(
            id=uuid4().hex,
            question=question,
            mode=mode,
            model_arn=model_arn,
            model_version_id=version_id,
            snapshot_sha256=snapshot_sha256,
            created_at=now,
            expires_at=now + BUDGET,
            warm_up=warm_up,
            warm_up_models=list(warm_up_models)
            if warm_up_models
            else (
                [PinnedModel(model_arn=model_arn, model_version_id=version_id)] if warm_up else []
            ),
        )
        if warm_up and not self.store.acquire_warm(job.id, now, job.expires_at):
            raise ValueError("Warm up is already active")
        if not self.store.save(job, 0):
            raise RuntimeError("Job identity collision")
        try:
            self.dispatch(job.id)
        except Exception:
            job.status, job.error = "failed", "Queue unavailable; submit again"
            self.store.save(job, 1)
            if warm_up:
                self.store.release_warm(job.id)
            raise RuntimeError("Queue unavailable") from None
        return job

    def get(self, id):
        for _ in range(3):
            job, rev = self.store.read(id)
            if job is None or job.status in TERMINAL or self.clock() < job.expires_at:
                return job
            job.status, job.error = "failed", "Job expired; submit again"
            if self.store.save(job, rev):
                if job.warm_up:
                    self.store.release_warm(job.id)
                return job
        raise RuntimeError("Job changed concurrently")


class Worker:
    def __init__(
        self, jobs: JobService, model_client, documents, *, clock=time.time, sleep=time.sleep
    ):
        self.jobs, self.model_client, self.documents = jobs, model_client, documents
        self.clock, self.sleep = clock, sleep

    def run(self, id):
        job = self.jobs.get(id)
        if job is None or job.status in TERMINAL:
            return
        job, rev = self.jobs.store.read(id)
        # Lease lasts until the immutable deadline. A duplicate never invokes the model.
        if job.status in TERMINAL or job.status in {"running", "warming"}:
            return
        job.status = "running"
        job.attempts += 1
        if not self.jobs.store.save(job, rev):
            raise RuntimeError("Job claimed concurrently")
        rev += 1

        def warming(_):
            nonlocal rev
            job.status = "warming"
            if not self.jobs.store.save(job, rev):
                raise RuntimeError("Job ownership lost")
            rev += 1

        try:
            documents = (
                self.documents(job.snapshot_sha256)
                if job.mode == "search" and not job.warm_up
                else ()
            )
            # Leave room for a final transport timeout before the fixed deadline.
            if self.clock() + 65 >= job.expires_at:
                raise TimeoutError

            def answerer():
                remaining = job.expires_at - self.clock() - 65
                if remaining < 0:
                    raise TimeoutError
                return Answerer(
                    self.model_client,
                    on_status=warming,
                    retry_seconds=min(840, remaining),
                    clock=self.clock,
                    sleep=self.sleep,
                )

            if job.warm_up:
                started = self.clock()
                # One delivery owns the whole sequence; base always precedes trained.
                for model in job.warm_up_models:
                    warming("warming")
                    result = answerer().warm_up(model.model_arn)
                result.answer = "Models are ready."
                result.latency_ms = (self.clock() - started) * 1000
            elif job.mode == "without":
                result = answerer().answer_without(job.question, job.model_arn)
            elif job.mode == "with":
                result = answerer().answer_with(job.question, job.model_arn)
            else:
                result = answerer().answer_search(
                    job.question,
                    job.model_arn,
                    documents.documents,
                    approved_quotes=documents.approved_quotes,
                )
            if self.clock() >= job.expires_at:
                raise TimeoutError
            job.status, job.answer = "succeeded", result.answer
            job.latency_ms = result.latency_ms
            job.citations = [c.model_dump(mode="json") for c in result.citations]
        except ModelWarming:
            job.status, job.error = "failed", "Model is still warming; use Warm up and try again"
        except Exception:
            # SDK messages may include prompt text, credentials or internal details.
            job.status, job.error = "failed", "Answer failed; submit again"
        try:
            if not self.jobs.store.save(job, rev):
                raise RuntimeError("Job ownership lost")
        finally:
            if job.warm_up:
                self.jobs.store.release_warm(job.id)

    def handle(self, event):
        failures = []
        for record in event.get("Records", []):
            try:
                self.run(json.loads(record["body"])["job_id"])
            except Exception:
                failures.append({"itemIdentifier": record["messageId"]})
        return {"batchItemFailures": failures}
