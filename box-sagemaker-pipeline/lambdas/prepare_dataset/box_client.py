"""Minimal Box API client using only the Python standard library.

Auth: Box Client Credentials Grant (CCG). The Secrets Manager secret must be JSON:
    {
      "client_id": "...",
      "client_secret": "...",
      "enterprise_id": "..."
    }
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import boto3

BOX_API = "https://api.box.com/2.0"
BOX_TOKEN_URL = "https://api.box.com/oauth2/token"


class BoxError(Exception):
    pass


class BoxClient:
    def __init__(self, access_token: str):
        self._token = access_token

    # ------------------------------------------------------------------ auth
    @classmethod
    def from_secret(cls, secret_name: str) -> "BoxClient":
        raw = boto3.client("secretsmanager").get_secret_value(SecretId=secret_name)["SecretString"]
        cfg = json.loads(raw)
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "box_subject_type": "enterprise",
                "box_subject_id": cfg["enterprise_id"],
            }
        ).encode()
        req = urllib.request.Request(BOX_TOKEN_URL, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return cls(json.loads(resp.read())["access_token"])

    # --------------------------------------------------------------- helpers
    def _request(self, url: str, headers: dict | None = None, retries: int = 3) -> bytes:
        for attempt in range(retries):
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {self._token}")
            for k, v in (headers or {}).items():
                req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                # Back off on rate limiting / transient server errors.
                if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                    time.sleep(int(e.headers.get("Retry-After", 2 ** attempt)))
                    continue
                raise BoxError(f"Box API {e.code} for {url}: {e.read()[:300]!r}") from e
        raise BoxError(f"Box API retries exhausted for {url}")

    def _get_json(self, url: str, headers: dict | None = None) -> dict:
        return json.loads(self._request(url, headers))

    # ------------------------------------------------------------ public API
    def get_text(self, file_id: str, timeout_s: int = 60) -> str:
        """Return the file's extracted text via Box's `extracted_text` representation.

        Works for PDFs, Office docs, etc. Falls back to raw content for plain text files.
        """
        info = self._get_json(
            f"{BOX_API}/files/{file_id}?fields=name,representations",
            headers={"X-Rep-Hints": "[extracted_text]"},
        )
        entries = info.get("representations", {}).get("entries", [])
        rep = next((e for e in entries if e.get("representation") == "extracted_text"), None)

        if rep is None:
            # No text representation (e.g. .txt / .md) - read raw bytes.
            return self._request(f"{BOX_API}/files/{file_id}/content").decode("utf-8", errors="ignore")

        deadline = time.time() + timeout_s
        while rep["status"]["state"] in ("pending", "none"):
            if time.time() > deadline:
                raise BoxError(f"extracted_text not ready for file {file_id}")
            time.sleep(2)
            rep = self._get_json(rep["info"]["url"])

        if rep["status"]["state"] != "success":
            raise BoxError(f"extracted_text failed for file {file_id}: {rep['status']}")

        url = rep["content"]["url_template"].replace("{+asset_path}", "")
        return self._request(url).decode("utf-8", errors="ignore")

    def get_validated_label(self, file_id: str, template: str) -> dict:
        """Return the validated target fields stored in the file's metadata template."""
        md = self._get_json(f"{BOX_API}/files/{file_id}/metadata/enterprise/{template}")
        # Drop Box system keys ($id, $type, $parent, ...).
        return {k: v for k, v in md.items() if not k.startswith("$")}
