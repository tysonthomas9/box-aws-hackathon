"""Official generated SDK adapter, with an explicit folder boundary and versioned reads."""

from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zipfile import ZipFile

from box_sdk_gen import BoxClient as SDKClient
from box_sdk_gen.managers.folders import CreateFolderParent
from box_sdk_gen.managers.uploads import (
    UploadFileAttributes,
    UploadFileAttributesParentField,
    UploadFileVersionAttributes,
)
from box_sdk_gen.managers.webhooks import (
    CreateWebhookTarget,
    CreateWebhookTargetTypeField,
    CreateWebhookTriggers,
)
from box_sdk_gen.networking.network import NetworkSession
from box_sdk_gen.networking.retries import BoxRetryStrategy

from kloop.box.auth import TokenProvider
from kloop.schemas import Document

FILE_FIELDS = ["id", "type", "name", "file_version", "parent", "path_collection", "etag", "sha1"]
MAX_TEXT_BYTES = 5 * 1024 * 1024


def document_text(body: bytes, name: str) -> str:
    """Read plain text or bounded DOCX paragraphs, including table cells, in order."""
    if not name.lower().endswith(".docx"):
        return body.decode("utf-8")
    with ZipFile(BytesIO(body)) as archive:
        member = archive.getinfo("word/document.xml")
        if member.file_size > MAX_TEXT_BYTES:
            raise ValueError("Box Word text exceeds the 5 MiB limit")
        xml = archive.read(member)
    # ElementTree does not fetch external entities; reject internal entity expansion too.
    if b"\x00" in xml or b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ValueError("Word document contains an unsupported XML declaration")
    root = ElementTree.fromstring(xml)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(ns + "p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == ns + "t":
                parts.append(node.text or "")
            elif node.tag == ns + "tab":
                parts.append("\t")
            elif node.tag in {ns + "br", ns + "cr"}:
                parts.append("\n")
        paragraphs.append("".join(parts))
    text = "\n".join(paragraphs)
    if not text.strip():
        raise ValueError("Word document contains no supported text")
    return text


@dataclass(frozen=True)
class FileInfo:
    file_id: str
    version_id: str
    name: str
    etag: str | None


def sdk_client(provider: TokenProvider) -> SDKClient:
    """SDK owns retries: bounded jittered backoff, Retry-After, CCG token renewal."""
    return SDKClient(
        provider.get_auth(),
        network_session=NetworkSession(retry_strategy=BoxRetryStrategy(max_attempts=4)),
    )


class BoxClient:
    def __init__(self, client: Any, folder_id: str) -> None:
        if not folder_id or folder_id == "0":
            raise ValueError("Configure a non-root Halvard folder")
        self.sdk = client
        self.folder_id = folder_id

    def _in_scope(self, item: Any, *, folder: bool = False) -> None:
        if folder and item.id == self.folder_id:
            return
        parent = getattr(item, "parent", None)
        paths = getattr(item, "path_collection", None)
        ancestors = {entry.id for entry in (getattr(paths, "entries", None) or [])}
        if (parent and parent.id == self.folder_id) or self.folder_id in ancestors:
            return
        raise PermissionError("Box item is outside the configured Halvard folder")

    def _file(self, file_id: str) -> Any:
        item = self.sdk.files.get_file_by_id(file_id, fields=FILE_FIELDS)
        self._in_scope(item)
        return item

    @staticmethod
    def _info(item: Any) -> FileInfo:
        if not item.file_version or not item.file_version.id:
            raise ValueError("Box did not return the file version")
        return FileInfo(item.id, item.file_version.id, item.name, item.etag)

    def get_file(self, file_id: str) -> FileInfo:
        return self._info(self._file(file_id))

    def list_folder(self, folder_id: str | None = None) -> list[Any]:
        folder_id = folder_id or self.folder_id
        if folder_id != self.folder_id:
            folder = self.sdk.folders.get_folder_by_id(folder_id, fields=["id", "path_collection"])
            self._in_scope(folder, folder=True)
        marker = None
        entries = []
        while True:
            page = self.sdk.folders.get_folder_items(
                folder_id, fields=FILE_FIELDS, usemarker=True, marker=marker, limit=1000
            )
            entries.extend(page.entries or [])
            if not page.next_marker:
                return entries
            if page.next_marker == marker:
                raise RuntimeError("Box returned a repeated pagination marker")
            marker = page.next_marker

    def _download(self, item: Any, version_id: str) -> Document:
        if not version_id:
            raise ValueError("A pinned Box version is required")
        stream = self.sdk.downloads.download_file(item.id, version=version_id)
        if stream is None:
            raise ValueError("Box did not return file content")
        with stream:
            body = stream.read(MAX_TEXT_BYTES + 1)
        if len(body) > MAX_TEXT_BYTES:
            raise ValueError("Box text exceeds the 5 MiB limit")
        return Document(
            file_id=item.id,
            version_id=version_id,
            name=item.name,
            text=document_text(body, item.name),
        )

    def get_document(self, file_id: str, version_id: str) -> Document:
        return self._download(self._file(file_id), version_id)

    def download_text(self, file_id: str, version_id: str | None = None) -> str:
        item = self._file(file_id)
        return self._download(item, version_id or self._info(item).version_id).text

    def list_documents(self, folder_id: str) -> list[Document]:
        return [
            self._download(entry, self._info(entry).version_id)
            for entry in self.list_folder(folder_id)
            if entry.type == "file"
        ]

    def upload_text(self, name: str, text: str, *, folder_id: str | None = None) -> FileInfo:
        target = folder_id or self.folder_id
        if target != self.folder_id:
            self._in_scope(
                self.sdk.folders.get_folder_by_id(target, fields=["id", "path_collection"]),
                folder=True,
            )
        with BytesIO(text.encode("utf-8")) as stream:
            result = self.sdk.uploads.upload_file(
                UploadFileAttributes(name, UploadFileAttributesParentField(target)),
                stream,
                file_file_name=name,
                file_content_type="text/plain; charset=utf-8",
                fields=FILE_FIELDS,
            )
        return self._info(result.entries[0])

    def upload_version(
        self, file_id: str, text: str, *, expected_etag: str | None = None
    ) -> FileInfo:
        current = self._file(file_id)
        etag = current.etag if expected_etag is None else expected_etag
        if not etag:
            raise ValueError("A version upload requires the inspected ETag")
        with BytesIO(text.encode("utf-8")) as stream:
            result = self.sdk.uploads.upload_file_version(
                file_id,
                UploadFileVersionAttributes(current.name),
                stream,
                file_file_name=current.name,
                file_content_type="text/plain; charset=utf-8",
                fields=FILE_FIELDS,
                if_match=etag,
            )
        return self._info(result.entries[0])

    def delete_file(self, file_id: str) -> None:
        current = self._file(file_id)
        self.sdk.files.delete_file_by_id(file_id, if_match=current.etag)

    def create_folder(self, name: str) -> str:
        return self.sdk.folders.create_folder(name, CreateFolderParent(self.folder_id)).id

    def create_webhook(self, address: str) -> str:
        url = urlsplit(address)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Webhook address must be an HTTPS URL without credentials")
        return self.sdk.webhooks.create_webhook(
            CreateWebhookTarget(id=self.folder_id, type=CreateWebhookTargetTypeField.FOLDER),
            address,
            [
                CreateWebhookTriggers.FILE_UPLOADED,
                CreateWebhookTriggers.FILE_TRASHED,
                CreateWebhookTriggers.FILE_DELETED,
            ],
        ).id

    def delete_webhook(self, webhook_id: str) -> None:
        hook = self.sdk.webhooks.get_webhook_by_id(webhook_id)
        if not hook.target or hook.target.type != "folder" or hook.target.id != self.folder_id:
            raise PermissionError("Webhook does not target the configured Halvard folder")
        self.sdk.webhooks.delete_webhook_by_id(webhook_id)
