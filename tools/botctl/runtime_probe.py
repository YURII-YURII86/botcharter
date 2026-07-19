from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model import API_VERSION, now_iso


def _process_check(pid: int) -> dict[str, Any]:
    if pid <= 0:
        raise ValueError("PID must be a positive integer")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        state = "not_running"
    except PermissionError:
        state = "running_not_owned"
    else:
        state = "running"
    return {"kind": "process", "status": "passed" if state != "not_running" else "failed", "pid": pid, "state": state}


def _heartbeat_check(path: Path, max_age_seconds: int) -> dict[str, Any]:
    if max_age_seconds <= 0:
        raise ValueError("max heartbeat age must be positive")
    resolved = Path(os.path.abspath(path.expanduser()))
    try:
        info = resolved.lstat()
    except FileNotFoundError:
        return {"kind": "heartbeat", "status": "failed", "path": str(resolved), "state": "missing", "max_age_seconds": max_age_seconds}
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return {"kind": "heartbeat", "status": "failed", "path": str(resolved), "state": "not_regular_file", "max_age_seconds": max_age_seconds}
    age = max(0.0, datetime.now(timezone.utc).timestamp() - info.st_mtime)
    fresh = age <= max_age_seconds
    return {
        "kind": "heartbeat",
        "status": "passed" if fresh else "warning",
        "path": str(resolved),
        "state": "fresh" if fresh else "stale",
        "age_seconds": round(age, 3),
        "max_age_seconds": max_age_seconds,
        "size_bytes": info.st_size,
    }


def probe_local_runtime(*, pid: int | None = None, heartbeat_file: Path | None = None, max_heartbeat_age: int = 300) -> dict[str, Any]:
    if pid is None and heartbeat_file is None:
        raise ValueError("provide --pid and/or --heartbeat-file")
    checks: list[dict[str, Any]] = []
    if pid is not None:
        checks.append(_process_check(pid))
    if heartbeat_file is not None:
        checks.append(_heartbeat_check(heartbeat_file, max_heartbeat_age))
    failures = sum(item["status"] == "failed" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    status = "failed" if failures else "degraded" if warnings else "passed"
    return {
        "apiVersion": API_VERSION,
        "kind": "BotLocalRuntimeProbe",
        "generated_at": now_iso(),
        "read_only": True,
        "scope": "local_metadata_only",
        "summary": {"status": status, "failures": failures, "warnings": warnings, "checks": len(checks)},
        "checks": checks,
        "safety": {
            "reads_secrets": False,
            "reads_file_contents": False,
            "reads_databases": False,
            "contacts_network": False,
            "sends_runtime_signals": False,
            "restarts_runtime": False,
            "writes_runtime": False,
        },
    }
