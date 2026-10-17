"""Build a Linux CPython 3.12 x86_64 zip; fail before the Lambda size ceiling."""

import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    build = ROOT / ".build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kloop-package-") as directory:
        target = Path(directory)
        # Deployment-only requirements also exercise the API/sync package gate.
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python-version",
                "3.12",
                "--python-platform",
                "x86_64-manylinux2014",
                "--only-binary",
                ":all:",
                "--no-compile-bytecode",
                "--target",
                str(target),
                "--require-hashes",
                "--requirement",
                str(ROOT / "infra/lambda-requirements.txt"),
            ],
            check=True,
        )
        for source in ("kloop", "lambdas"):
            shutil.copytree(
                ROOT / source,
                target / source,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        dev = Path("poc/model-experiment/data/dev.jsonl")
        (target / dev).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / dev, target / dev)
        size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
        if size >= 220 * 1024 * 1024:
            raise RuntimeError(
                f"Package is {size} bytes; switch to a container image before deploy"
            )
        with zipfile.ZipFile(build / "lambda.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    entry = zipfile.ZipInfo(str(path.relative_to(target)), (1980, 1, 1, 0, 0, 0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.external_attr = 0o644 << 16
                    archive.writestr(entry, path.read_bytes())
        report = {
            "platform": "manylinux2014_x86_64",
            "python": "3.12",
            "unpacked_bytes": size,
            "zip_bytes": (build / "lambda.zip").stat().st_size,
            "threshold_bytes": 220 * 1024 * 1024,
        }
        # Linux native wheels cannot be imported by macOS. Run on Lambda after deployment.
        (build / "package-size.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
