#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def tree_hash(project: Path, *, exclude_control: bool = False) -> str:
    digest = hashlib.sha256()
    for path in sorted(project.rglob("*")):
        if exclude_control and ".botctl" in path.parts:
            continue
        if path.is_file():
            digest.update(str(path.relative_to(project)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def run(command: list[str], cwd: Path, *, expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode not in expected:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the private-infrastructure-free botctl public alpha demo")
    parser.add_argument("--botctl", help="Installed botctl executable to verify instead of the source runner")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "examples" / "existing-service"
    with tempfile.TemporaryDirectory(prefix="botctl-public-demo-") as raw:
        project = Path(raw) / "existing-service"
        shutil.copytree(source, project)
        cli = [str(Path(args.botctl).expanduser().resolve())] if args.botctl else [sys.executable, str(root / "tools" / "botctl.py")]
        before = tree_hash(project)

        preview = run(cli + ["adopt", "--project", str(project), "--format", "json"], root)
        preview_payload = json.loads(preview.stdout)
        if preview_payload["status"] != "ready_to_adopt" or tree_hash(project) != before:
            raise RuntimeError("adoption preview was not read-only")

        outside_before = tree_hash(project, exclude_control=True)
        adopted = run(cli + ["adopt", "--project", str(project), "--confirm", "--format", "json"], root)
        adopted_payload = json.loads(adopted.stdout)
        if adopted_payload["status"] != "adopted" or adopted_payload["verify_summary"]["errors"] != 0:
            raise RuntimeError("confirmed adoption did not verify")
        if tree_hash(project, exclude_control=True) != outside_before:
            raise RuntimeError("adoption changed files outside .botctl")
        if len(list((project / ".botctl" / "specs").glob("*.yaml"))) != 6:
            raise RuntimeError("adoption did not create six local specs")

        audit = run(cli + ["audit-runtime", "--project", str(project), "--specs", str(project / ".botctl" / "specs"), "--format", "json"], root)
        audit_payload = json.loads(audit.stdout)
        repeated_before = tree_hash(project)
        repeated = run(cli + ["adopt", "--project", str(project), "--confirm", "--format", "json"], root)
        if json.loads(repeated.stdout)["status"] != "already_adopted" or tree_hash(project) != repeated_before:
            raise RuntimeError("repeated adoption was not idempotent")

        print("botctl public alpha demo")
        print("- preview_read_only: passed")
        print("- confirmed_adoption: passed")
        print("- outside_botctl_unchanged: passed")
        print("- local_specs: 6")
        print(f"- verify_errors: {adopted_payload['verify_summary']['errors']}")
        print(f"- source_audit_status: {audit_payload['summary']['status']}")
        print("- repeat_idempotent: passed")
        print("public_alpha_demo=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
