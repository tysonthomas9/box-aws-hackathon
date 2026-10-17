"""SDK-shaped fakes and redacted POC 3 metadata fixtures; no network credentials."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from box_sdk_gen import BoxClient as SDKClient
from box_sdk_gen import BoxDeveloperTokenAuth, FileFull, Webhook
from box_sdk_gen.box.errors import BoxAPIError
from box_sdk_gen.networking.box_network_client import APIResponse
from box_sdk_gen.networking.fetch_response import FetchResponse
from box_sdk_gen.networking.network import NetworkSession
from box_sdk_gen.networking.network_client import NetworkClient
from requests import Response

from kloop.adapters.memory import MemoryStorage
from kloop.box import (
    BoxClient,
    CCGTokenProvider,
    DeveloperTokenProvider,
    sdk_client,
    token_provider,
    verify_webhook,
)
from kloop.box.client import MAX_TEXT_BYTES
from kloop.box.seed import DEFAULT_PACK, seed
from kloop.config import Settings

FIXTURES = Path(__file__).parent / "fixtures/box"
FOLDER = "428389178330"
FILE = "2532291966730"
VERSION = "2810011275730"
NOW = datetime(2026, 10, 17, 6, 0, tzinfo=UTC)


def file_info(**overrides):
    return FileFull.from_dict({**json.loads((FIXTURES / "file.json").read_text()), **overrides})


@pytest.fixture
def fake():
    sdk = SimpleNamespace(
        **{name: Mock() for name in ("files", "folders", "downloads", "uploads", "webhooks")}
    )
    sdk.files.get_file_by_id.return_value = file_info()
    sdk.downloads.download_file.side_effect = lambda *_a, **_k: BytesIO(b"old text")
    sdk.folders.get_folder_items.return_value = SimpleNamespace(
        entries=[file_info()], next_marker=None
    )
    sdk.uploads.upload_file.return_value = SimpleNamespace(entries=[file_info()])
    sdk.uploads.upload_file_version.return_value = SimpleNamespace(entries=[file_info()])
    sdk.webhooks.get_webhook_by_id.return_value = Webhook.from_dict(
        json.loads((FIXTURES / "webhook.json").read_text())
    )
    return sdk


def test_current_and_pinned_old_version(fake):
    client = BoxClient(fake, FOLDER)
    assert client.get_file(FILE).version_id == VERSION
    assert client.get_document(FILE, "old-version").text == "old text"
    fake.downloads.download_file.assert_called_with(FILE, version="old-version")
    assert client.download_text(FILE) == "old text"
    fake.downloads.download_file.assert_called_with(FILE, version=VERSION)


def test_marker_pagination_and_skip_folders(fake):
    fake.folders.get_folder_items.side_effect = [
        SimpleNamespace(entries=[file_info()], next_marker="page2"),
        SimpleNamespace(entries=[SimpleNamespace(type="folder")], next_marker=None),
    ]
    docs = BoxClient(fake, FOLDER).list_documents(FOLDER)
    assert len(docs) == 1 and docs[0].version_id == VERSION
    assert fake.folders.get_folder_items.call_args.kwargs["marker"] == "page2"
    assert fake.folders.get_folder_items.call_args.kwargs["usemarker"] is True


def test_repeated_marker_rejected(fake):
    fake.folders.get_folder_items.return_value = SimpleNamespace(entries=[], next_marker="same")
    with pytest.raises(RuntimeError):
        BoxClient(fake, FOLDER).list_folder()


@pytest.mark.parametrize(
    "operation", ["get_file", "download_text", "delete_file", "upload_version"]
)
def test_file_scope_denied_before_content_or_write(fake, operation):
    fake.files.get_file_by_id.return_value = file_info(parent={"id": "elsewhere", "type": "folder"})
    args = (FILE, "replacement") if operation == "upload_version" else (FILE,)
    with pytest.raises(PermissionError):
        getattr(BoxClient(fake, FOLDER), operation)(*args)
    fake.files.delete_file_by_id.assert_not_called()
    fake.uploads.upload_file_version.assert_not_called()
    fake.downloads.download_file.assert_not_called()


def test_descendant_scope_and_etag_guard(fake):
    fake.files.get_file_by_id.return_value = file_info(
        parent={"id": "child", "type": "folder"},
        path_collection={"total_count": 1, "entries": [{"id": FOLDER, "type": "folder"}]},
    )
    BoxClient(fake, FOLDER).delete_file(FILE)
    fake.files.delete_file_by_id.assert_called_once_with(FILE, if_match="2")


@pytest.mark.parametrize("folder", ["", "0"])
def test_root_not_accepted(fake, folder):
    with pytest.raises(ValueError):
        BoxClient(fake, folder)


def test_other_folder_list_upload_denied(fake):
    fake.folders.get_folder_by_id.return_value = SimpleNamespace(id="other", path_collection=None)
    client = BoxClient(fake, FOLDER)
    with pytest.raises(PermissionError):
        client.list_folder("other")
    with pytest.raises(PermissionError):
        client.upload_text("name.txt", "text", folder_id="other")
    fake.folders.get_folder_items.assert_not_called()
    fake.uploads.upload_file.assert_not_called()


def test_upload_and_version_streams_closed(fake):
    streams = []

    def upload(*args, **kwargs):
        stream = args[-1]
        assert stream.read() == b"new text"
        streams.append(stream)
        return SimpleNamespace(entries=[file_info()])

    fake.uploads.upload_file.side_effect = upload
    fake.uploads.upload_file_version.side_effect = upload
    client = BoxClient(fake, FOLDER)
    client.upload_text("name.txt", "new text")
    client.upload_version(FILE, "new text")
    assert all(stream.closed for stream in streams)
    assert fake.uploads.upload_file_version.call_args.kwargs["if_match"] == "2"
    assert fake.uploads.upload_file.call_args.args[0].parent.id == FOLDER


def test_download_stream_closed_on_bad_utf8_and_size(fake):
    stream = BytesIO(b"\xff")
    fake.downloads.download_file.side_effect = None
    fake.downloads.download_file.return_value = stream
    with pytest.raises(UnicodeError):
        BoxClient(fake, FOLDER).download_text(FILE)
    assert stream.closed
    stream = BytesIO(b"x" * (MAX_TEXT_BYTES + 1))
    fake.downloads.download_file.return_value = stream
    with pytest.raises(ValueError, match="limit"):
        BoxClient(fake, FOLDER).download_text(FILE)
    assert stream.closed


def test_download_interruption_closes_stream(fake):
    class Interrupted(BytesIO):
        def read(self, *_):
            raise OSError("interrupted")

    stream = Interrupted()
    fake.downloads.download_file.side_effect = None
    fake.downloads.download_file.return_value = stream
    with pytest.raises(OSError):
        BoxClient(fake, FOLDER).download_text(FILE)
    assert stream.closed


def test_webhook_scope_create_delete(fake):
    client = BoxClient(fake, FOLDER)
    client.create_webhook("https://receiver.example.test/api/box-webhook")
    assert fake.webhooks.create_webhook.call_args.args[0].id == FOLDER
    client.delete_webhook("8516747068")
    fake.webhooks.delete_webhook_by_id.assert_called_once_with("8516747068")
    fake.webhooks.get_webhook_by_id.return_value.target.id = "unrelated"
    with pytest.raises(PermissionError):
        client.delete_webhook("other")
    assert fake.webhooks.delete_webhook_by_id.call_count == 1


@pytest.mark.parametrize("url", ["http://bad.test", "https://user:secret@bad.test", "https://"])
def test_webhook_url_validation(fake, url):
    with pytest.raises(ValueError):
        BoxClient(fake, FOLDER).create_webhook(url)
    fake.webhooks.create_webhook.assert_not_called()


def delivery(
    body=b'{"event":"test"}',
    timestamp="2026-10-17T06:00:00+00:00",
    key="test-only-key",
    slot="primary",
):
    signature = base64.b64encode(hmac.digest(key.encode(), body + timestamp.encode(), "sha256"))
    return {"BOX-DELIVERY-TIMESTAMP": timestamp, f"Box-Signature-{slot}": signature.decode()}


def test_signature_known_vector():
    body = b'{"event":"test"}'
    headers = delivery(body)
    # Fixed independently generated vector locks down raw body + ISO timestamp + Base64.
    assert headers["Box-Signature-primary"] == "EHwoEXVTTFhTLF1StMvijqPzvV2Whs4f9a+PfL5p5hA="
    assert verify_webhook(body, headers, primary_key="test-only-key", now=NOW)
    assert not verify_webhook(body + b" ", headers, primary_key="test-only-key", now=NOW)
    assert not verify_webhook(body, headers, now=NOW)
    assert not verify_webhook(body, {}, primary_key="test-only-key", now=NOW)


def test_signature_secondary_rotation_and_case_insensitive_headers():
    body = b'{"event":"test"}'
    headers = delivery(body, key="secondary", slot="secondary")
    headers["Box-Signature-primary"] = "invalid"
    assert verify_webhook(body, headers, primary_key="wrong", secondary_key="secondary", now=NOW)
    assert not verify_webhook(body, headers, primary_key="secondary", now=NOW)
    headers["box-signature-version"] = "2"
    assert not verify_webhook(body, headers, secondary_key="secondary", now=NOW)


@pytest.mark.parametrize("offset,valid", [(-601, False), (-600, True), (0, True), (1, False)])
def test_signature_freshness(offset, valid):
    stamp = (NOW + timedelta(seconds=offset)).isoformat()
    assert (
        verify_webhook(
            b'{"event":"test"}', delivery(timestamp=stamp), primary_key="test-only-key", now=NOW
        )
        is valid
    )


@pytest.mark.parametrize("stamp", ["bad", "2026-10-17", "", "2026-10-17T06:00:00"])
def test_bad_timestamp(stamp):
    assert not verify_webhook(
        b'{"event":"test"}', delivery(timestamp=stamp), primary_key="test-only-key", now=NOW
    )


def test_bad_signature_algorithm_and_non_ascii():
    headers = delivery()
    headers["box-signature-algorithm"] = "HmacSHA1"
    assert not verify_webhook(b'{"event":"test"}', headers, primary_key="test-only-key", now=NOW)
    headers.pop("box-signature-algorithm")
    headers["Box-Signature-primary"] = "\N{SNOWMAN}"
    assert not verify_webhook(b'{"event":"test"}', headers, primary_key="test-only-key", now=NOW)


@pytest.mark.parametrize("subject", ["user", "enterprise"])
def test_ccg_subject_from_secret_and_auth_reused(subject):
    provider = CCGTokenProvider(
        {
            "client_id": "client",
            "client_secret": "test-only",
            "box_subject_type": subject,
            "box_subject_id": "subject-id",
        }
    )
    auth = provider.get_auth()
    assert auth is provider.get_auth()
    assert auth.subject_type == subject
    assert auth.subject_id == "subject-id"


def test_auth_defaults_ccg_never_silently_uses_developer_token():
    secrets = Mock()
    secrets.get_secret_value.return_value = {
        "SecretString": json.dumps({"developer_token": "test"})
    }
    with pytest.raises(ValueError, match="CCG"):
        token_provider(secrets, Settings())
    assert isinstance(token_provider(secrets, Settings(), mode="developer"), DeveloperTokenProvider)
    secrets.get_secret_value.assert_called_with(SecretId="box-hackathon/box-ccg")
    with pytest.raises(ValueError):
        DeveloperTokenProvider("")


def test_sdk_metadata_fixture_deserialization_and_required_fields():
    calls = []

    class Recorded(NetworkClient):
        def fetch(self, options):
            calls.append(options)
            return FetchResponse(200, {}, data=json.loads((FIXTURES / "file.json").read_text()))

    sdk = SDKClient(
        BoxDeveloperTokenAuth("test-only"),
        network_session=NetworkSession(network_client=Recorded()),
    )
    info = BoxClient(sdk, FOLDER).get_file(FILE)
    assert info.version_id == VERSION
    assert "file_version" in calls[0].params["fields"]
    assert calls[0].url.endswith("/files/" + FILE)


def test_sdk_retry_after_and_bounded_backoff(monkeypatch):
    sdk = sdk_client(DeveloperTokenProvider("test-only"))
    transport = sdk.network_session.network_client
    attempts = []
    waits = []

    def response(request):
        attempts.append(request)
        reply = Response()
        reply.status_code = 429
        reply.headers["Retry-After"] = "3"
        reply._content = b'{"code":"rate_limit_exceeded"}'
        return APIResponse(network_response=reply)

    monkeypatch.setattr(transport, "_make_request", response)
    monkeypatch.setattr("box_sdk_gen.networking.box_network_client.time.sleep", waits.append)
    with pytest.raises(BoxAPIError):
        sdk.files.get_file_by_id(FILE)
    assert len(attempts) == 4
    assert waits == [3, 3, 3]
    strategy = sdk.network_session.retry_strategy
    retry = FetchResponse(429, {})
    # Default jitter is 0.5, exponential retry interval at attempt 3 is 8 seconds.
    assert 4 <= strategy.retry_after(None, retry, 3) <= 12


def test_seed_pack_repeat_is_stable_and_records_ids(fake):
    files = {}
    bodies = {}
    fake.folders.get_folder_items.side_effect = lambda *_a, **_k: SimpleNamespace(
        entries=list(files.values()), next_marker=None
    )

    def upload(attrs, stream, **kwargs):
        id = str(len(files) + 1)
        item = file_info(id=id, name=attrs.name)
        files[attrs.name] = item
        bodies[id] = stream.read()
        return SimpleNamespace(entries=[item])

    fake.uploads.upload_file.side_effect = upload
    fake.files.get_file_by_id.side_effect = lambda id, **_k: next(
        f for f in files.values() if f.id == id
    )
    fake.downloads.download_file.side_effect = lambda id, **_k: BytesIO(bodies[id])
    storage = MemoryStorage()
    client = BoxClient(fake, FOLDER)
    first = seed(client, storage=storage)
    second = seed(client, storage=storage)
    assert first == second
    assert len(files) == 13
    assert fake.uploads.upload_file.call_count == 13
    fake.uploads.upload_file_version.assert_not_called()
    assert storage.get("box_seed", "halvard") == first
    assert len(storage.list("box_sources")) == 13
    assert first["pack_sha256"] == hashlib.sha256(DEFAULT_PACK.read_bytes()).hexdigest()
    assert b"below 4 bar" in bodies[files["e42.txt"].id]


def test_ccg_wire_request_caches_token_and_renews_after_rejection():
    calls = []

    class TokenEndpoint(NetworkClient):
        def fetch(self, options):
            calls.append(options)
            return FetchResponse(
                200,
                {},
                data={
                    "access_token": f"test-token-{len(calls)}",
                    "expires_in": 3600,
                    "token_type": "bearer",
                },
            )

    provider = CCGTokenProvider(
        {
            "client_id": "client",
            "client_secret": "test-only",
            "box_subject_type": "user",
            "box_subject_id": "subject-id",
        }
    )
    session = NetworkSession(network_client=TokenEndpoint())
    auth = provider.get_auth()
    assert auth.retrieve_authorization_header(network_session=session) == "Bearer test-token-1"
    assert auth.retrieve_authorization_header(network_session=session) == "Bearer test-token-1"
    assert len(calls) == 1
    assert calls[0].data["grant_type"] == "client_credentials"
    assert calls[0].data["box_subject_type"] == "user"
    assert calls[0].data["box_subject_id"] == "subject-id"
    assert calls[0].data["client_secret"] == "test-only"
    auth.refresh_token(network_session=session)
    assert auth.retrieve_authorization_header(network_session=session) == "Bearer test-token-2"


def test_seed_changed_source_uses_new_version(fake, tmp_path):
    pack_path = tmp_path / "pack.json"
    pack_path.write_text(
        json.dumps(
            {"facts": [{"source": "kestrel.txt", "text": "changed value"}], "procedures": []}
        )
    )
    text = b"old text"

    def upload_version(_id, _attrs, stream, **kwargs):
        nonlocal text
        text = stream.read()
        return SimpleNamespace(entries=[file_info(file_version={"id": "new-version"})])

    fake.uploads.upload_file_version.side_effect = upload_version
    fake.downloads.download_file.side_effect = lambda *_a, **_k: BytesIO(text)
    result = seed(BoxClient(fake, FOLDER), pack_path)
    assert result["files"][0]["version_id"] == "new-version"
    fake.uploads.upload_file.assert_not_called()
    fake.uploads.upload_file_version.assert_called_once()
