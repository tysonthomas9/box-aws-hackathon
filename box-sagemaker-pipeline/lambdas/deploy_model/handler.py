"""DeployModel Lambda: deploys a trained model to Amazon Bedrock (Custom Model Import).

Invoked by the state machine with an "action":

  start    -> CreateModelImportJob from the merged HF weights in S3. Returns job_arn.
  status   -> GetModelImportJob. Returns status (InProgress|Completed|Failed) and,
              when completed, the imported model ARN.
  register -> Records the new model as "live" in an SSM parameter (simple model
              registry - consumers read it to find the current model ARN), then
              deletes older pipeline models beyond KEEP_MODELS (Bedrock allows only
              a few imported models per account; the kept ones are rollback targets).
"""
import datetime as dt
import json
import os

import boto3

IMPORT_ROLE_ARN = os.environ["IMPORT_ROLE_ARN"]
PARAM_NAME = os.environ["LIVE_MODEL_PARAM"]
MODEL_PREFIX = os.environ["MODEL_NAME_PREFIX"]
KEEP_MODELS = int(os.environ.get("KEEP_MODELS", "2"))

_bedrock = boto3.client("bedrock")
_ssm = boto3.client("ssm")


def _start(event: dict) -> dict:
    resp = _bedrock.create_model_import_job(
        jobName=event["import_job_name"],
        importedModelName=event["imported_model_name"],
        roleArn=IMPORT_ROLE_ARN,
        modelDataSource={"s3DataSource": {"s3Uri": event["weights_s3_uri"]}},
        jobTags=[{"key": "pipeline", "value": "box-sagemaker-pipeline"}],
        importedModelTags=[{"key": "pipeline", "value": "box-sagemaker-pipeline"}],
    )
    return {"job_arn": resp["jobArn"]}


def _status(event: dict) -> dict:
    job = _bedrock.get_model_import_job(jobIdentifier=event["job_arn"])
    out = {"job_arn": job["jobArn"], "status": job["status"]}
    if job["status"] == "Completed":
        out["model_arn"] = job["importedModelArn"]
        out["model_name"] = job["importedModelName"]
    if job["status"] == "Failed":
        out["failure_message"] = job.get("failureMessage", "")
    return out


def _pipeline_models() -> list[dict]:
    models, kwargs = [], {"nameContains": MODEL_PREFIX}
    while True:
        resp = _bedrock.list_imported_models(**kwargs)
        models += [m for m in resp.get("modelSummaries", []) if m["modelName"].startswith(MODEL_PREFIX)]
        if not resp.get("nextToken"):
            return sorted(models, key=lambda m: m["creationTime"], reverse=True)
        kwargs["nextToken"] = resp["nextToken"]


def _register(event: dict) -> dict:
    model_arn = event["model_arn"]
    record = {
        "model_arn": model_arn,
        "model_name": event.get("model_name"),
        "run_id": event.get("run_id"),
        "training_job": event.get("training_job"),
        "weights_s3_uri": event.get("weights_s3_uri"),
        "registered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _ssm.put_parameter(Name=PARAM_NAME, Value=json.dumps(record), Type="String", Overwrite=True)

    deleted = []
    for m in _pipeline_models()[KEEP_MODELS:]:
        if m["modelArn"] == model_arn:  # never delete the model we just registered
            continue
        _bedrock.delete_imported_model(modelIdentifier=m["modelArn"])
        deleted.append(m["modelName"])
    return {"live_model": record, "deleted_old_models": deleted}


_ACTIONS = {"start": _start, "status": _status, "register": _register}


def lambda_handler(event, _context):
    action = event.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {sorted(_ACTIONS)}")
    return _ACTIONS[action](event)
