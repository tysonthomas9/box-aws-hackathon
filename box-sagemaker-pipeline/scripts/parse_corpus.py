#!/usr/bin/env python3
"""Extract plain text from the downloaded Box corpus (docx, pdf, htm, txt, json).

Usage: python scripts/parse_corpus.py /tmp/box_corpus /tmp/box_corpus/parsed.jsonl
Each output line: {"path", "folder", "name", "chars", "text"}
"""
import html
import json
import os
import re
import sys
import zipfile


def docx_text(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)          # paragraph breaks
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"</w:tc>", " | ", xml)        # table cells
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def pdf_text(path: str) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)


def htm_text(path: str) -> str:
    raw = open(path, encoding="utf-8", errors="ignore").read()
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", raw)
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def json_text(path: str) -> str:
    return json.dumps(json.load(open(path, encoding="utf-8", errors="ignore")), indent=1, ensure_ascii=False)


PARSERS = {"docx": docx_text, "pdf": pdf_text, "htm": htm_text, "html": htm_text, "txt": None, "json": json_text}


def clean(t: str) -> str:
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


def main(root: str, out_path: str) -> None:
    rows, errors = [], []
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            if name in ("manifest.json", os.path.basename(out_path)):
                continue
            path = os.path.join(dirpath, name)
            ext = name.rsplit(".", 1)[-1].lower()
            try:
                fn = PARSERS.get(ext, "unsupported")
                if fn == "unsupported":
                    raise ValueError(f"unsupported extension .{ext}")
                text = open(path, encoding="utf-8", errors="ignore").read() if fn is None else fn(path)
                text = clean(text)
                rel = os.path.relpath(path, root)
                rows.append({"path": rel, "folder": os.path.dirname(rel), "name": name, "chars": len(text), "text": text})
            except Exception as e:  # keep going; report at the end
                errors.append((os.path.relpath(path, root), repr(e)[:200]))
    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"parsed {len(rows)} files -> {out_path}; errors: {len(errors)}")
    for e in errors:
        print("  ERROR", e)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
