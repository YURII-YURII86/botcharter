#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / "tools" / "botctl.py"), "probe-runtime"]
    schema = json.loads((root / "schemas" / "runtime-probe.schema.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as raw:
        heartbeat = Path(raw) / "heartbeat"
        heartbeat.write_text("content-must-not-be-read", encoding="utf-8")
        heartbeat.chmod(0)
        result = subprocess.run(
            command + ["--pid", str(os.getpid()), "--heartbeat-file", str(heartbeat), "--format", "json"],
            cwd=root, text=True, capture_output=True,
        )
        payload = json.loads(result.stdout)
        jsonschema.Draft202012Validator(schema).validate(payload)
        safe = result.returncode == 0 and payload["summary"]["status"] == "passed" and all(value is False for value in payload["safety"].values())
        heartbeat.chmod(0o600)
        link = Path(raw) / "heartbeat-link"
        link.symlink_to(heartbeat)
        linked = subprocess.run(command + ["--heartbeat-file", str(link), "--format", "json"], cwd=root, text=True, capture_output=True)
        linked_payload = json.loads(linked.stdout)
        symlink_ok = linked.returncode != 0 and linked_payload["checks"][0]["state"] == "not_regular_file"
        os.utime(heartbeat, (1, 1))
        stale = subprocess.run(command + ["--heartbeat-file", str(heartbeat), "--max-heartbeat-age", "1", "--format", "json"], cwd=root, text=True, capture_output=True)
        stale_payload = json.loads(stale.stdout)
        stale_ok = stale.returncode == 0 and stale_payload["summary"]["status"] == "degraded"
    missing = subprocess.run(
        command + ["--heartbeat-file", str(root / ".tmp" / "definitely-missing-heartbeat"), "--format", "json"],
        cwd=root, text=True, capture_output=True,
    )
    missing_payload = json.loads(missing.stdout)
    missing_ok = missing.returncode != 0 and missing_payload["summary"]["status"] == "failed"
    empty = subprocess.run(command, cwd=root, text=True, capture_output=True)
    empty_ok = empty.returncode != 0
    print(f"runtime_probe_safe_ok={safe}")
    print(f"runtime_probe_missing_guard_ok={missing_ok}")
    print(f"runtime_probe_explicit_target_guard_ok={empty_ok}")
    print(f"runtime_probe_symlink_guard_ok={symlink_ok}")
    print(f"runtime_probe_stale_warning_ok={stale_ok}")
    passed = safe and missing_ok and empty_ok and symlink_ok and stale_ok
    print("runtime_probe_smoke=passed" if passed else "runtime_probe_smoke=failed")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
