import io
import json

import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from pydantic import ValidationError

from kloop.adapters.aws import BedrockModelClient
from kloop.adapters.memory import FakeBoxClient, FakeModelClient
from kloop.config import Settings
from kloop.schemas import Document


def test_bedrock_invocation(aws_session):
    client = aws_session.client("bedrock-runtime")
    payload = {"prompt": "Who?", "max_tokens": 32}
    result = {"choices": [{"text": "Mara"}]}
    encoded = json.dumps(result).encode()
    stream = io.BytesIO(encoded)
    body = StreamingBody(stream, len(encoded))
    with Stubber(client) as stubber:
        stubber.add_response(
            "invoke_model",
            {"body": body, "contentType": "application/json"},
            {
                "modelId": "test-model",
                "body": json.dumps(payload),
                "contentType": "application/json",
                "accept": "application/json",
            },
        )
        assert BedrockModelClient(client).invoke("test-model", payload) == result
        stubber.assert_no_pending_responses()
    assert stream.closed


def test_bedrock_errors_propagate(aws_session):
    client = aws_session.client("bedrock-runtime")
    with Stubber(client) as stubber:
        stubber.add_client_error("invoke_model", service_error_code="AccessDeniedException")
        with pytest.raises(client.exceptions.AccessDeniedException):
            BedrockModelClient(client).invoke("test-model", {})


def test_fake_model_records_calls():
    fake = FakeModelClient("Mara")
    payload = {"prompt": "Who?"}
    assert fake.invoke("base", payload) == {"choices": [{"text": "Mara"}]}
    payload["prompt"] = "Changed"
    assert fake.calls == [("base", {"prompt": "Who?"})]


def test_fake_box_versions_and_copy_isolation():
    doc = Document(file_id="1", version_id="v1", name="Policy", text="Call Mara")
    fake = FakeBoxClient({"folder": [doc, doc.model_copy(update={"version_id": "v2"})]})
    doc.text = "Changed"
    assert fake.get_document("1", "v1").text == "Call Mara"
    result = fake.list_documents("folder")
    result[0].text = "Changed again"
    assert fake.get_document("1", "v1").text == "Call Mara"
    assert fake.get_document("1", "v2").version_id == "v2"
    assert fake.list_documents("unknown") == []
    with pytest.raises(KeyError):
        fake.get_document("1", "missing")


def test_env_config(monkeypatch):
    monkeypatch.setenv("KLOOP_TABLE_NAME", "test-table")
    monkeypatch.setenv("KLOOP_ARTIFACT_BUCKET", "test-bucket")
    settings = Settings()
    assert settings.table_name == "test-table"
    assert settings.artifact_bucket == "test-bucket"
    assert settings.region == "us-east-2"
    monkeypatch.setenv("KLOOP_REGION", "us-west-2")
    with pytest.raises(ValidationError):
        Settings()
