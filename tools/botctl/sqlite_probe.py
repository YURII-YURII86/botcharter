from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .model import API_VERSION, now_iso


def _metadata(path: Path) -> tuple[int, int, int, int]:
    info = path.lstat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _sidecar_metadata(path: Path) -> dict[str, tuple[int, int, int, int] | None]:
    return {suffix: _metadata(Path(str(path) + suffix)) if Path(str(path) + suffix).exists() else None for suffix in ("-journal", "-wal", "-shm")}


def _path_fingerprint(path: Path) -> str:
    return "sha256:" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]


def probe_sqlite_integrity(*, database: Path, confirm_database_read: bool) -> dict[str, Any]:
    if not confirm_database_read:
        raise ValueError("database access requires --confirm-database-read")
    path = Path(os.path.abspath(database.expanduser()))
    if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise ValueError("database must use .db, .sqlite, or .sqlite3 suffix")
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("database must be a regular non-symlink file")
    before = _metadata(path)
    sidecars_before = _sidecar_metadata(path)
    state = "invalid_or_corrupt"
    try:
        uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            connection.execute("PRAGMA query_only = ON")
            row = connection.execute("PRAGMA quick_check(1)").fetchone()
            state = "ok" if row and row[0] == "ok" else "invalid_or_corrupt"
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        state = "invalid_or_corrupt"
    after = _metadata(path)
    sidecars_after = _sidecar_metadata(path)
    unchanged = before == after and sidecars_before == sidecars_after
    passed = state == "ok" and unchanged
    return {
        "apiVersion": API_VERSION,
        "kind": "BotSqliteIntegrityProbe",
        "generated_at": now_iso(),
        "read_only": True,
        "scope": "explicit_sqlite_quick_check",
        "target": {"path": str(path), "path_fingerprint": _path_fingerprint(path), "size_bytes": info.st_size},
        "summary": {"status": "passed" if passed else "failed"},
        "check": {"state": state, "metadata_unchanged": unchanged},
        "safety": {
            "database_read_explicitly_confirmed": True,
            "sqlite_mode": "ro_immutable",
            "query_only": True,
            "reads_user_rows": False,
            "outputs_schema": False,
            "accepts_user_sql": False,
            "writes_database": False,
        },
    }
