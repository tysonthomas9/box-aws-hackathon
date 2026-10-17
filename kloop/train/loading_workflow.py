"""Bounded reload workflow, with a single readiness-triggered re-import."""

import json


def definition(worker):
    def task(action, next):
        return {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": worker,
                "Payload": {"action": action, "version_id.$": "$.version_id", "owner.$": "$.owner"},
            },
            "ResultSelector": {"value.$": "$.Payload"},
            "ResultPath": "$.result",
            "TimeoutSeconds": 900,
            "Next": next,
        }

    work = {
        "Create": task("create", "Wait"),
        "Wait": {"Type": "Wait", "Seconds": 30, "Next": "Poll"},
        "Poll": task("poll", "Status"),
        "Status": {
            "Type": "Choice",
            "Choices": [
                {"Variable": "$.result.value.status", "StringEquals": "Completed", "Next": "Warm"},
                {"Variable": "$.result.value.status", "StringEquals": "Failed", "Next": "Failed"},
            ],
            "Default": "Wait",
        },
        "Warm": task("warm", "Done"),
        "Reimport": task("reimport", "ReimportStatus"),
        "ReimportStatus": {
            "Type": "Choice",
            "Choices": [
                {"Variable": "$.result.value.complete", "BooleanEquals": True, "Next": "Create"}
            ],
            "Default": "WaitDelete",
        },
        "WaitDelete": {"Type": "Wait", "Seconds": 30, "Next": "Reimport"},
        "Done": {"Type": "Succeed"},
        "Failed": {"Type": "Fail", "Error": "ImportFailed"},
    }
    work["Warm"]["Catch"] = [
        {"ErrorEquals": ["ModelWarming"], "ResultPath": "$.warm_error", "Next": "Reimport"}
    ]
    finish = task("finish", "Done")
    fail = task("fail", "CleanupStatus")
    return {
        "StartAt": "Work",
        "TimeoutSeconds": 7200,
        "States": {
            "Work": {
                "Type": "Parallel",
                "Branches": [{"StartAt": "Create", "States": work}],
                "ResultPath": None,
                "Next": "Finish",
                "Catch": [
                    {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Cleanup"}
                ],
            },
            "Finish": finish,
            "Done": {"Type": "Succeed"},
            "Cleanup": fail,
            "CleanupStatus": {
                "Type": "Choice",
                "Choices": [
                    {"Variable": "$.result.value.complete", "BooleanEquals": True, "Next": "Failed"}
                ],
                "Default": "WaitCleanup",
            },
            "WaitCleanup": {"Type": "Wait", "Seconds": 30, "Next": "Cleanup"},
            "Failed": {"Type": "Fail", "Error": "VersionLoadFailed"},
        },
    }


if __name__ == "__main__":
    print(json.dumps(definition("${worker_arn}"), indent=2))
