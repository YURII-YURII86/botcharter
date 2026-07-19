#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml


REQUIRED = {
    "README.md", "README.ru.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md",
    "docs/PUBLIC_ALPHA.md", "docs/RELEASE_CHECKLIST.md", "pyproject.toml", "MANIFEST.in",
}
FORBIDDEN_PATH_MARKERS = tuple("/" + part for part in ("Users/", "Volumes/", "mnt/usb/")) + ("C:" + "\\Users\\",)
PATH_POLICY_FILES = {"tools/release_check.py", "docs/RELEASE_CHECKLIST.md"}
FORBIDDEN_FILE_RE = re.compile(r"(^|/)(\.env(?:\..*)?|.*\.(?:pem|key|p12|pfx|sqlite3?|db|session|log)|credentials?[^/]*|secrets?[^/]*)$", re.I)
SECRET_PATTERNS = {
    "private key": re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Telegram bot token": re.compile(r"(?<!\d)\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),
    "local-host email": re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.local\b", re.I),
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors: list[str] = []
    missing = sorted(name for name in REQUIRED if not (root / name).is_file())
    if missing:
        errors.append("missing required files: " + ", ".join(missing))
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root, text=True, capture_output=True, check=True,
    ).stdout.splitlines()
    for relative in tracked:
        if FORBIDDEN_FILE_RE.search(relative):
            errors.append(f"sensitive filename is tracked: {relative}")
        if relative in PATH_POLICY_FILES:
            continue
        path = root / relative
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in FORBIDDEN_PATH_MARKERS:
            if marker in text:
                errors.append(f"machine-specific path marker {marker!r} in {relative}")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"potential {label} in {relative}")
    for profile in (root / "profiles").glob("*/profile.yaml"):
        text = profile.read_text(encoding="utf-8").lower()
        if "synthetic" not in profile.parent.name or "fictional" not in text:
            errors.append(f"public profile is not explicitly fictional: {profile.relative_to(root)}")
    for path in (root / "schemas").glob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid JSON {path.relative_to(root)}: {exc}")
    for path in list((root / "specs").glob("*.yaml")) + list((root / "profiles").glob("**/*.yaml")):
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid YAML {path.relative_to(root)}: {exc}")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    if 'name = "botcharter"' not in pyproject or "0.8.0a1" not in pyproject or 'license = "MIT"' not in pyproject:
        errors.append("pyproject public-alpha version/license metadata is incomplete")
    package_init = (root / "tools" / "botctl" / "__init__.py").read_text(encoding="utf-8")
    if '__version__ = "0.8.0a1"' not in package_init:
        errors.append("CLI and package version are not synchronized")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"release_check_errors={len(errors)}")
    print("release_check=passed" if not errors else "release_check=failed")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
