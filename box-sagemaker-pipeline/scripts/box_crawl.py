#!/usr/bin/env python3
"""Crawl a public Box shared folder (no API credentials) and optionally download files.

Box share pages embed the folder listing as JSON; this walks subfolders and pages.

Usage:
    python scripts/box_crawl.py <share_url> --out /tmp/box_corpus [--download] [--limit N]
Writes <out>/manifest.json: [{path, file_id, name, size}]
"""
import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}


def get(url: str) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def _items(page: str) -> list[dict]:
    """Extract item objects (typedID + name + size) from the embedded page JSON."""
    out = {}
    for m in re.finditer(r'"typedID":"([fd]_\d+)"', page):
        # Walk back to the start of the enclosing {...} object and forward to its end.
        start = page.rfind("{", 0, m.start())
        depth, end = 0, start
        for i in range(start, min(len(page), start + 20000)):
            if page[i] == "{":
                depth += 1
            elif page[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            obj = json.loads(page[start:end])
        except json.JSONDecodeError:
            continue
        if "name" in obj:
            out[obj["typedID"]] = {"typed_id": obj["typedID"], "name": obj["name"], "size": obj.get("itemSize")}
    return list(out.values())


def crawl(share_hash: str, folder_id: str, path: str, seen: set, results: list) -> None:
    if folder_id in seen:
        return
    seen.add(folder_id)
    page_no, page_count = 1, 1
    while page_no <= page_count:
        url = f"https://app.box.com/s/{share_hash}/folder/{folder_id}?page={page_no}"
        page = get(url).decode("utf-8", "ignore")
        pc = re.search(r'"pageCount":(\d+)', page)
        page_count = int(pc.group(1)) if pc else 1
        for it in _items(page):
            tid = it["typed_id"]
            if tid == f"d_{folder_id}":
                continue
            if tid.startswith("f_"):
                results.append({"path": f"{path}/{it['name']}", "file_id": tid[2:], "name": it["name"], "size": it["size"]})
            elif tid.startswith("d_"):
                # Only descend into children (skip breadcrumb ancestors, which appear in the page too).
                child_marker = re.search(rf'"typedID":"{tid}"[^{{}}]*"parentID":"?{folder_id}"?', page) or \
                               re.search(rf'"parentID":"?{folder_id}"?[^{{}}]*"typedID":"{tid}"', page)
                if child_marker or tid not in {f"d_{x}" for x in seen}:
                    crawl(share_hash, tid[2:], f"{path}/{it['name']}", seen, results)
        page_no += 1


def download(share_hash: str, file_id: str) -> bytes:
    q = urllib.parse.urlencode({"rm": "box_download_shared_file", "shared_name": share_hash, "file_id": f"f_{file_id}"})
    return get(f"https://app.box.com/index.php?{q}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("share_url")
    ap.add_argument("--out", required=True)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="download at most N files (0 = all)")
    args = ap.parse_args()

    share_hash = urllib.parse.urlparse(args.share_url).path.rstrip("/").split("/s/")[1].split("/")[0]
    root_page = get(f"https://app.box.com/s/{share_hash}").decode("utf-8", "ignore")
    root_id = re.search(r'"currentFolderID":"?(\d+)', root_page).group(1)

    results, seen = [], set()
    crawl(share_hash, root_id, "", seen, results)
    # Dedupe by file id (ancestors can be revisited via breadcrumbs).
    results = list({r["file_id"]: r for r in results}.values())
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump({"share_hash": share_hash, "root_folder_id": root_id, "files": results}, f, indent=1)
    print(f"found {len(results)} files in {len(seen)} folders")

    if args.download:
        todo = results[: args.limit] if args.limit else results
        for r in todo:
            dest = os.path.join(args.out, r["path"].lstrip("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(download(share_hash, r["file_id"]))
        print(f"downloaded {len(todo)} files to {args.out}")


if __name__ == "__main__":
    main()
