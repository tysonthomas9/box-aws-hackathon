"""Unit tests for the DeployModel Lambda (Bedrock + SSM mocked)."""
import datetime as dt
import importlib.util
import json
import os
import unittest
from unittest import mock

# Hermetic: never pick up a developer's real AWS profile/credentials.
for _k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
    os.environ.pop(_k, None)
os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing")
os.environ.update(
    IMPORT_ROLE_ARN="arn:aws:iam::111111111111:role/import",
    LIVE_MODEL_PARAM="/box-sagemaker-pipeline/live-model",
    MODEL_NAME_PREFIX="pharma-qwen-",
    KEEP_MODELS="2",
    AWS_DEFAULT_REGION="us-east-2",
)
_spec = importlib.util.spec_from_file_location(
    "deploy_handler", os.path.join(os.path.dirname(__file__), "..", "lambdas", "deploy_model", "handler.py")
)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


def _model(name, day):
    return {"modelName": name, "modelArn": f"arn:aws:bedrock:us-east-2:1:imported-model/{name}",
            "creationTime": dt.datetime(2026, 10, day, tzinfo=dt.timezone.utc)}


class DeployModelTest(unittest.TestCase):
    def setUp(self):
        self.bedrock, self.ssm = mock.MagicMock(), mock.MagicMock()
        for name, val in (("_bedrock", self.bedrock), ("_ssm", self.ssm)):
            p = mock.patch.object(handler, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_start_creates_import_job(self):
        self.bedrock.create_model_import_job.return_value = {"jobArn": "arn:job/1"}
        out = handler.lambda_handler({"action": "start", "import_job_name": "j", "imported_model_name": "pharma-qwen-x",
                                      "weights_s3_uri": "s3://b/models/x/hf/"}, None)
        self.assertEqual(out, {"job_arn": "arn:job/1"})
        kw = self.bedrock.create_model_import_job.call_args.kwargs
        self.assertEqual(kw["modelDataSource"]["s3DataSource"]["s3Uri"], "s3://b/models/x/hf/")
        self.assertEqual(kw["roleArn"], os.environ["IMPORT_ROLE_ARN"])

    def test_status_completed_returns_model_arn(self):
        self.bedrock.get_model_import_job.return_value = {
            "jobArn": "arn:job/1", "status": "Completed", "importedModelArn": "arn:m", "importedModelName": "pharma-qwen-x"}
        out = handler.lambda_handler({"action": "status", "job_arn": "arn:job/1"}, None)
        self.assertEqual(out["status"], "Completed")
        self.assertEqual(out["model_arn"], "arn:m")

    def test_status_in_progress_has_no_model(self):
        self.bedrock.get_model_import_job.return_value = {"jobArn": "arn:job/1", "status": "InProgress"}
        out = handler.lambda_handler({"action": "status", "job_arn": "arn:job/1"}, None)
        self.assertEqual(out, {"job_arn": "arn:job/1", "status": "InProgress"})

    def test_register_writes_param_and_keeps_newest_two(self):
        models = [_model("pharma-qwen-a", 1), _model("pharma-qwen-c", 3), _model("pharma-qwen-b", 2),
                  _model("other-model", 4)]
        self.bedrock.list_imported_models.return_value = {"modelSummaries": models}
        new_arn = models[1]["modelArn"]  # pharma-qwen-c (newest)
        out = handler.lambda_handler({"action": "register", "model_arn": new_arn, "model_name": "pharma-qwen-c"}, None)

        put = self.ssm.put_parameter.call_args.kwargs
        self.assertEqual(json.loads(put["Value"])["model_arn"], new_arn)
        self.assertTrue(put["Overwrite"])
        # keeps c, b; deletes a; never touches non-pipeline models
        self.assertEqual(out["deleted_old_models"], ["pharma-qwen-a"])
        self.bedrock.delete_imported_model.assert_called_once_with(modelIdentifier=models[0]["modelArn"])

    def test_unknown_action_raises(self):
        with self.assertRaises(ValueError):
            handler.lambda_handler({"action": "nope"}, None)


if __name__ == "__main__":
    unittest.main()
