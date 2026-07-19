#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.iterdir()):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / "tools" / "botctl.py"), "probe-sqlite"]
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        database = tmp / "fixture.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE private_data(secret TEXT)")
        connection.execute("INSERT INTO private_data VALUES ('must-never-appear-in-output')")
        connection.commit()
        connection.close()
        before = tree_hash(tmp)
        blocked = subprocess.run(command + ["--database", str(database)], cwd=root, text=True, capture_output=True)
        result = subprocess.run(command + ["--database", str(database), "--confirm-database-read", "--format", "json"], cwd=root, text=True, capture_output=True)
        after = tree_hash(tmp)
        payload = json.loads(result.stdout)
        schema = json.loads((root / "schemas" / "sqlite-probe.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)
        secret_safe = "must-never-appear-in-output" not in result.stdout and "private_data" not in result.stdout
        read_only_ok = result.returncode == 0 and before == after and payload["check"]["metadata_unchanged"] is True and secret_safe
        link = tmp / "linked.sqlite3"
        link.symlink_to(database)
        linked = subprocess.run(command + ["--database", str(link), "--confirm-database-read"], cwd=root, text=True, capture_output=True)
    passed = blocked.returncode != 0 and linked.returncode != 0 and read_only_ok
    print(f"sqlite_probe_confirmation_guard_ok={blocked.returncode != 0}")
    print(f"sqlite_probe_symlink_guard_ok={linked.returncode != 0}")
    print(f"sqlite_probe_read_only_hash_ok={read_only_ok}")
    print("sqlite_probe_smoke=passed" if passed else "sqlite_probe_smoke=failed")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
