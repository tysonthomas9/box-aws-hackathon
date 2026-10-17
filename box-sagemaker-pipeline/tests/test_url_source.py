"""Tests for url_source (host allowlist, JSON validation) and the test_data files."""
import glob
import io
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "lambdas", "prepare_dataset"))

import url_source  # noqa: E402
from url_source import UrlFetchError, fetch_example  # noqa: E402

REQUIRED_OUTPUT_KEYS = {
    "doc_type", "issuing_organization", "document_date", "products", "active_ingredients",
    "therapeutic_area", "key_requirements", "safety_signals", "compliance_deadline",
    "risk_level", "action_required", "summary",
}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class UrlSourceTest(unittest.TestCase):
    def _open(self, body: bytes):
        return mock.patch.object(url_source._opener, "open", return_value=_Resp(body))

    def test_rejects_non_box_and_http(self):
        for bad in ("https://evil.example.com/a.json", "http://app.box.com/shared/static/a.json",
                    "https://box.com.evil.io/a.json", "https://169.254.169.254/latest/meta-data"):
            with self.assertRaises(UrlFetchError, msg=bad):
                fetch_example(bad)

    def test_accepts_valid_box_json(self):
        body = json.dumps({"input": "text", "output": {"doc_type": "x"}}).encode()
        with self._open(body):
            text, label = fetch_example("https://app.box.com/shared/static/a.json")
        self.assertEqual(text, "text")
        self.assertEqual(label, {"doc_type": "x"})

    def test_html_share_page_gives_hint(self):
        with self._open(b"<!DOCTYPE html><html>"):
            with self.assertRaisesRegex(UrlFetchError, "direct/static link"):
                fetch_example("https://app.box.com/shared/static/abc")

    def test_share_link_resolved_to_download_endpoint(self):
        page = b'<html>..."typedID":"f_12345"...</html>'
        body = json.dumps({"input": "t", "output": {"doc_type": "x"}}).encode()
        calls = []

        def fake_open(req, timeout=60):
            calls.append(req.full_url)
            return _Resp(page if len(calls) == 1 else body)

        with mock.patch.object(url_source._opener, "open", side_effect=fake_open):
            fetch_example("https://app.box.com/s/abc123")
        self.assertEqual(calls[0], "https://app.box.com/s/abc123")
        self.assertIn("rm=box_download_shared_file", calls[1])
        self.assertIn("shared_name=abc123", calls[1])
        self.assertIn("file_id=f_12345", calls[1])

    def test_share_link_without_file_id_errors(self):
        with self._open(b"<html>no id here</html>"):
            with self.assertRaisesRegex(UrlFetchError, "file id"):
                fetch_example("https://app.box.com/s/abc")

    def test_missing_fields_rejected(self):
        with self._open(json.dumps({"input": "only text"}).encode()):
            with self.assertRaises(UrlFetchError):
                fetch_example("https://app.box.com/shared/static/a.json")

    def test_redirect_to_non_box_blocked(self):
        h = url_source._BoxOnlyRedirectHandler()
        with self.assertRaises(UrlFetchError):
            h.redirect_request(None, None, 302, "", {}, "https://evil.example.com/x")


class TestDataFilesTest(unittest.TestCase):
    def test_all_files_are_training_ready(self):
        files = sorted(glob.glob(os.path.join(HERE, "..", "test_data", "*.json")))
        self.assertEqual(len(files), 10)
        for path in files:
            with open(path) as f:
                doc = json.load(f)
            self.assertIsInstance(doc["input"], str, path)
            self.assertTrue(doc["input"].strip(), path)
            self.assertEqual(set(doc["output"]), REQUIRED_OUTPUT_KEYS, path)
            self.assertIn(doc["output"]["risk_level"], {"low", "medium", "high"}, path)


if __name__ == "__main__":
    unittest.main()
