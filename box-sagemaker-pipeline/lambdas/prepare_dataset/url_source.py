"""Fetch a training-ready JSON document from a Box shared (public) URL.

Each document must be JSON with:
    {"input": "<document text>", "output": {<validated structured label>}}

Only Box-owned hosts are allowed, so DynamoDB rows cannot make the Lambda
fetch arbitrary URLs (SSRF protection). Use Box *direct* links
(https://app.box.com/shared/static/<id>.json) - the regular /s/<id> share
page returns HTML, not the file.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOST_SUFFIXES = (".box.com", ".boxcloud.com")
MAX_BYTES = 5 * 1024 * 1024


class UrlFetchError(Exception):
    pass


def _host_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == s.lstrip(".") or host.endswith(s) for s in ALLOWED_HOST_SUFFIXES
    )


class _BoxOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _host_allowed(newurl):
            raise UrlFetchError(f"Redirect to non-Box host blocked: {urllib.parse.urlparse(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_BoxOnlyRedirectHandler)

_SHARE_PATH = re.compile(r"^/s/([A-Za-z0-9]+)/?$")
_TYPED_ID = re.compile(rb'"typedID":"f_(\d+)"')


def _get(url: str, limit: int) -> bytes:
    try:
        with _opener.open(urllib.request.Request(url), timeout=60) as resp:
            return resp.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise UrlFetchError(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        raise UrlFetchError(f"Network error fetching {url}: {e.reason}") from e


def _resolve_download_url(url: str) -> str:
    """Turn a Box share-page link (app.box.com/s/<hash>) into a direct download URL.

    The share page embeds the file ID; Box's shared-file download endpoint then
    redirects to public.boxcloud.com with the file bytes. Static links pass through.
    Note: this relies on Box's web page markup, which is fine for a demo but may change.
    """
    parsed = urllib.parse.urlparse(url)
    m = _SHARE_PATH.match(parsed.path)
    if not m:
        return url
    shared_name = m.group(1)
    page = _get(url, 2 * 1024 * 1024)
    fid = _TYPED_ID.search(page)
    if not fid:
        raise UrlFetchError(f"Could not find file id in Box share page (folder link or download disabled?): {url}")
    query = urllib.parse.urlencode(
        {"rm": "box_download_shared_file", "shared_name": shared_name, "file_id": f"f_{fid.group(1).decode()}"}
    )
    return f"https://{parsed.hostname}/index.php?{query}"


def fetch_example(url: str) -> tuple[str, dict]:
    """Return (input_text, output_label) from a Box shared URL."""
    if not _host_allowed(url):
        raise UrlFetchError(f"URL host not allowed (Box https only): {url}")
    body = _get(_resolve_download_url(url), MAX_BYTES)
    if len(body) > MAX_BYTES:
        raise UrlFetchError(f"File larger than {MAX_BYTES} bytes: {url}")
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as e:
        hint = " (got HTML - use the Box direct/static link)" if body.lstrip()[:1] == b"<" else ""
        raise UrlFetchError(f"Not valid JSON{hint}: {url}") from e

    text, label = doc.get("input"), doc.get("output")
    if not isinstance(text, str) or not text.strip() or not isinstance(label, dict) or not label:
        raise UrlFetchError(f"JSON must contain non-empty 'input' (str) and 'output' (object): {url}")
    return text, label
