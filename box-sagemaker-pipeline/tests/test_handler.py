"""Unit tests for the PrepareDataset Lambda. AWS and Box are fully mocked."""
import io
import json
import os
import sys
import unittest
from unittest import mock

# Hermetic: never pick up a developer's real AWS profile/credentials.
for _k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
    os.environ.pop(_k, None)
os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing")
os.environ.update(
    TABLE_NAME="t",
    STATUS_INDEX="status-index",
    BUCKET_NAME="b",
    BOX_SECRET_NAME="s",
    BOX_METADATA_TEMPLATE="contractFields",
    MIN_NEW_EXAMPLES="2",
    AWS_DEFAULT_REGION="us-west-2",
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "prepare_dataset"))

import handler  # noqa: E402
from box_client import BoxError  # noqa: E402


class FakeS3:
    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self.exceptions.NoSuchKey()
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body


class PrepareDatasetTest(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        self.table = mock.MagicMock()
        self.box = mock.MagicMock()
        self.box.get_text.side_effect = lambda fid: f"text of {fid}"
        self.box.get_validated_label.side_effect = lambda fid, tpl: {"doc_type": "NDA", "id": fid}
        patches = [
            mock.patch.object(handler, "_s3", self.s3),
            mock.patch.object(handler, "_table", self.table),
            mock.patch.object(handler.BoxClient, "from_secret", return_value=self.box),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _rows(self, *ids):
        self.table.query.return_value = {"Items": [{"file_id": i, "status": "validated"} for i in ids]}

    def test_skips_when_not_enough_data(self):
        self._rows("f1")
        out = handler.lambda_handler({}, None)
        self.assertFalse(out["enough_data"])
        self.box.get_text.assert_not_called()
        self.table.update_item.assert_not_called()

    def test_builds_dataset_and_marks_trained(self):
        self._rows("f1", "f2")
        out = handler.lambda_handler({}, None)

        self.assertTrue(out["enough_data"])
        self.assertEqual(out["total_example_count"], 2)
        key = f"datasets/{out['run_id']}/train.jsonl"
        lines = self.s3.objects[key].decode().strip().split("\n")
        ex = json.loads(lines[0])
        self.assertEqual(ex["messages"][1]["role"], "assistant")
        self.assertEqual(json.loads(ex["messages"][1]["content"])["id"], "f1")
        self.assertEqual(self.table.update_item.call_count, 2)
        self.assertLessEqual(len(out["job_name"]), 63)

    def test_accumulates_previous_snapshot(self):
        self.s3.objects["datasets/old/train.jsonl"] = b'{"old": 1}\n'
        self.s3.objects[handler.LATEST_POINTER_KEY] = json.dumps({"train_key": "datasets/old/train.jsonl"}).encode()
        self._rows("f1", "f2")
        out = handler.lambda_handler({}, None)
        self.assertEqual(out["total_example_count"], 3)
        self.assertEqual(out["new_example_count"], 2)

    def test_url_rows_use_url_source_without_box_secret(self):
        self.table.query.return_value = {
            "Items": [
                {"file_id": "u1", "status": "validated", "source_url": "https://app.box.com/shared/static/a.json"},
                {"file_id": "u2", "status": "validated", "source_url": "https://app.box.com/shared/static/b.json"},
            ]
        }
        with mock.patch.object(handler, "fetch_example", return_value=("doc text", {"doc_type": "recall_notice"})) as fe, \
                mock.patch.object(handler.BoxClient, "from_secret") as fs:
            out = handler.lambda_handler({}, None)
        self.assertTrue(out["enough_data"])
        self.assertEqual(fe.call_count, 2)
        fs.assert_not_called()  # no Box API credentials needed for URL rows

    def test_prebuilt_dataset_skips_ddb_and_box(self):
        out = handler.lambda_handler({"prebuilt_train_s3_uri": "s3://b/datasets/corpus-v1"}, None)
        self.assertTrue(out["enough_data"])
        self.assertEqual(out["train_s3_uri"], "s3://b/datasets/corpus-v1/")
        self.assertIn("export_s3_uri", out)
        self.table.query.assert_not_called()

    def test_prebuilt_dataset_must_be_in_pipeline_bucket(self):
        with self.assertRaises(ValueError):
            handler.lambda_handler({"prebuilt_train_s3_uri": "s3://other-bucket/x/"}, None)

    def test_box_failure_leaves_row_validated(self):
        self._rows("f1", "f2", "f3")
        self.box.get_text.side_effect = lambda fid: (_ for _ in ()).throw(BoxError("x")) if fid == "f3" else "t"
        out = handler.lambda_handler({}, None)
        self.assertEqual(out["failed_files"], ["f3"])
        marked = [c.kwargs["Key"]["file_id"] for c in self.table.update_item.call_args_list]
        self.assertNotIn("f3", marked)


if __name__ == "__main__":
    unittest.main()
