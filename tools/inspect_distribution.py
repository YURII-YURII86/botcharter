#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from pathlib import Path


FORBIDDEN = tuple(b"/" + part for part in (b"Volumes/", b"mnt/usb/", b"Users/")) + (b"C:" + b"\\Users\\",)
SECRET_PATTERNS = (
    ("private key", re.compile(rb"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY")),
    ("GitHub token", re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("Telegram bot token", re.compile(rb"(?<!\d)\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
    ("local-host email", re.compile(rb"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.local\b", re.I)),
)
RUNTIME_REQUIRED = ("botctl/cli.py", "runtime-audit.schema.json", "profiles/synthetic-media-pipeline/specs/FLOWS.yaml")
SDIST_REQUIRED = ("README.md", "README.ru.md", "SECURITY.md", "CONTRIBUTING.md", "docs/PUBLIC_ALPHA.md", "tools/demo_public_alpha.py")


def inspect_archive(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            blobs = [archive.read(name) for name in names if not name.endswith("/")]
        required = RUNTIME_REQUIRED
    else:
        with tarfile.open(path) as archive:
            members = [member for member in archive.getmembers() if member.isfile()]
            names = [member.name for member in members]
            blobs = [archive.extractfile(member).read() for member in members]  # type: ignore[union-attr]
        required = RUNTIME_REQUIRED + SDIST_REQUIRED
    errors = [f"missing {item}" for item in required if not any(item in name for name in names)]
    errors.extend(f"contains forbidden path marker {marker.decode()}" for marker in FORBIDDEN if any(marker in blob for blob in blobs))
    errors.extend(f"contains potential {label}" for label, pattern in SECRET_PATTERNS if any(pattern.search(blob) for blob in blobs))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archives", nargs="+")
    args = parser.parse_args()
    total_errors = 0
    for raw in args.archives:
        path = Path(raw)
        errors = inspect_archive(path)
        total_errors += len(errors)
        print(f"{path.name}: {'passed' if not errors else 'failed'}")
        for error in errors:
            print(f"  ERROR: {error}")
    print(f"distribution_inspection_errors={total_errors}")
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
