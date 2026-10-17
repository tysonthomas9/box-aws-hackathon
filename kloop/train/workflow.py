"""ASL for a bounded Standard workflow; external aborts use recovery events."""

import json


def definition(worker_arn: str) -> dict:
    def task(action, next_state=None, *, seconds=900):
        value = {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": worker_arn,
                "Payload": {"action": action, "version_id.$": "$.version_id"},
            },
            "ResultSelector": {"value.$": "$.Payload"},
            "ResultPath": f"$.{action}",
            "TimeoutSeconds": seconds,
        }
        value.update({"Next": next_state} if next_state else {"End": True})
        return value

    work = {
        "Batches": task("batches", "Generate"),
        "Generate": {
            "Type": "Map",
            "ItemsPath": "$.batches.value.batches",
            "MaxConcurrency": 2,
            "Parameters": {
                "version_id.$": "$.version_id",
                "batch.$": "$$.Map.Item.Value",
                "generation_pass": 1,
            },
            "Iterator": {
                "StartAt": "GenerateBatch",
                "States": {
                    "GenerateBatch": task("generate", "GenerationPassStatus", seconds=840),
                    "GenerationPassStatus": {
                        "Type": "Choice",
                        "Choices": [
                            {
                                "Variable": "$.generate.value.complete",
                                "BooleanEquals": True,
                                "Next": "BatchComplete",
                            },
                            {
                                "Variable": "$.generation_pass",
                                "NumericGreaterThanEquals": 3,
                                "Next": "BatchComplete",
                            },
                        ],
                        "Default": "NextGenerationPass",
                    },
                    "NextGenerationPass": {
                        "Type": "Pass",
                        "Parameters": {
                            "version_id.$": "$.version_id",
                            "batch.$": "$.batch",
                            "generation_pass.$": "States.MathAdd($.generation_pass, 1)",
                        },
                        "Next": "GenerateBatch",
                    },
                    "BatchComplete": {"Type": "Pass", "End": True},
                },
            },
            "ResultPath": None,
            "Next": "Prepare",
        },
        "Prepare": task("prepare", "Train"),
        "Train": {
            "Type": "Task",
            "Resource": "arn:aws:states:::sagemaker:createTrainingJob.sync",
            "Parameters": {},
            "TimeoutSeconds": 8500,
            "ResultPath": None,
            "Next": "Import",
        },
        "Import": task("import", "WaitImport", seconds=60),
        "WaitImport": {"Type": "Wait", "Seconds": 30, "Next": "PollImport"},
        "PollImport": task("poll", "ImportStatus", seconds=60),
        "ImportStatus": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.poll.value.status",
                    "StringEquals": "Completed",
                    "Next": "WarmCurrent",
                },
                {
                    "Variable": "$.poll.value.status",
                    "StringEquals": "Failed",
                    "Next": "ImportFailed",
                },
            ],
            "Default": "CountPoll",
        },
        "CountPoll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.polls.count, 1)"},
            "ResultPath": "$.polls",
            "Next": "PollLimit",
        },
        "PollLimit": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.polls.count",
                    "NumericGreaterThanEquals": 90,
                    "Next": "ImportTimeout",
                }
            ],
            "Default": "WaitImport",
        },
        "ImportFailed": {"Type": "Fail", "Error": "ImportFailed"},
        "ImportTimeout": {"Type": "Fail", "Error": "ImportTimeout"},
        "WarmCurrent": task("warm_current", "Warm", seconds=900),
        "Warm": task("warm", "Evaluate", seconds=900),
        "Reimport": task("reimport", "ReimportStatus", seconds=60),
        "ReimportStatus": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.reimport.value.complete",
                    "BooleanEquals": True,
                    "Next": "WaitImport",
                }
            ],
            "Default": "WaitReimport",
        },
        "WaitReimport": {"Type": "Wait", "Seconds": 30, "Next": "Reimport"},
        "Evaluate": task("evaluate", "Gate", seconds=900),
        "Gate": {
            "Type": "Choice",
            "Choices": [
                {"Variable": "$.evaluate.value.passed", "BooleanEquals": True, "Next": "Promote"}
            ],
            "Default": "Rejected",
        },
        "Promote": task("promote"),
        "Rejected": {"Type": "Pass", "End": True},
    }
    work["Warm"]["Catch"] = [
        {"ErrorEquals": ["ModelWarming"], "ResultPath": "$.warm_error", "Next": "Reimport"}
    ]
    work["Generate"]["Iterator"]["States"]["GenerateBatch"]["Parameters"]["Payload"]["batch.$"] = (
        "$.batch"
    )
    work["Generate"]["Iterator"]["States"]["GenerateBatch"]["Parameters"]["Payload"][
        "generation_pass.$"
    ] = "$.generation_pass"
    # Retry only transient provider/invocation failures, resuming the same cached
    # batch. Recipe, overlap and budget failures must still stop before GPU.
    work["Generate"]["Iterator"]["States"]["GenerateBatch"]["Retry"] = [
        {
            "ErrorEquals": [
                "ThrottlingException",
                "ServiceUnavailableException",
                "InternalServerException",
                "Lambda.ServiceException",
                "Lambda.SdkClientException",
                "Lambda.TooManyRequestsException",
                "Lambda.AWSLambdaException",
            ],
            "IntervalSeconds": 30,
            "BackoffRate": 2,
            "MaxAttempts": 5,
            "MaxDelaySeconds": 120,
            "JitterStrategy": "FULL",
        }
    ]
    # Use static known request fields, passing only values from prepare. Entire
    # request includes explicit region-bound image, input channels and job name.
    for name in (
        "TrainingJobName",
        "RoleArn",
        "AlgorithmSpecification",
        "InputDataConfig",
        "OutputDataConfig",
        "ResourceConfig",
        "StoppingCondition",
        "EnableManagedSpotTraining",
        "Environment",
        "Tags",
    ):
        work["Train"]["Parameters"][name + ".$"] = f"$.prepare.value.request.{name}"
    cleanup = task("cleanup", "CleanupStatus", seconds=60)
    cleanup["Retry"] = [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 3}]
    # Cleanup exceptions MUST still release the lock; ledger reservations block
    # future training until recovery reconciles resources, even after release.
    cleanup["Catch"] = [
        {"ErrorEquals": ["States.ALL"], "ResultPath": "$.cleanup_error", "Next": "ReleaseFailure"}
    ]
    return {
        "Comment": "Training transaction; Standard required; recovery handles abort/timeouts",
        "StartAt": "Initialize",
        "TimeoutSeconds": 18000,
        "States": {
            "Initialize": {
                "Type": "Pass",
                "Result": {"count": 0},
                "ResultPath": "$.polls",
                "Next": "Transaction",
            },
            "Transaction": {
                "Type": "Parallel",
                "Branches": [{"StartAt": "Batches", "States": work}],
                "ResultPath": None,
                "Next": "Cleanup",
                "Catch": [
                    {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Cleanup"}
                ],
            },
            "Cleanup": cleanup,
            "CleanupStatus": {
                "Type": "Choice",
                "Choices": [
                    {
                        "Variable": "$.cleanup.value.complete",
                        "BooleanEquals": True,
                        "Next": "Release",
                    }
                ],
                "Default": "CountCleanup",
            },
            "CountCleanup": {
                "Type": "Pass",
                "Parameters": {"count.$": "States.MathAdd($.polls.count, 1)"},
                "ResultPath": "$.polls",
                "Next": "CleanupLimit",
            },
            "CleanupLimit": {
                "Type": "Choice",
                "Choices": [
                    {
                        "Variable": "$.polls.count",
                        "NumericGreaterThanEquals": 90,
                        "Next": "ReleaseFailure",
                    }
                ],
                "Default": "WaitCleanup",
            },
            "WaitCleanup": {"Type": "Wait", "Seconds": 30, "Next": "Cleanup"},
            "Release": task("release", "Outcome", seconds=60),
            "ReleaseFailure": task("release", "UnresolvedCleanup", seconds=60),
            "UnresolvedCleanup": {"Type": "Fail", "Error": "CleanupNeedsRecovery"},
            "Outcome": {
                "Type": "Choice",
                "Choices": [{"Variable": "$.error", "IsPresent": True, "Next": "Failed"}],
                "Default": "Done",
            },
            "Failed": {"Type": "Fail", "Error": "TrainingFailed"},
            "Done": {"Type": "Succeed"},
        },
    }


def main():
    print(json.dumps(definition("${worker_arn}"), indent=2))


if __name__ == "__main__":
    main()
